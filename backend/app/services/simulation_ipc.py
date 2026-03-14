"""
Módulo de comunicação IPC para simulação
Usado para comunicação entre processos do backend Flask e scripts de simulação

Implementa um padrão simples de comando/resposta via sistema de arquivos:
1. Flask escreve comandos no diretório commands/
2. Script de simulação faz polling no diretório de comandos, executa e escreve resposta no diretório responses/
3. Flask faz polling no diretório de respostas para obter resultados
"""

import os
import json
import time
import uuid
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from ..utils.logger import get_logger

logger = get_logger('checksimulator.simulation_ipc')


class CommandType(str, Enum):
    """Tipo de comando"""
    INTERVIEW = "interview"           # Entrevista de um único Agent
    BATCH_INTERVIEW = "batch_interview"  # Entrevista em lote
    CLOSE_ENV = "close_env"           # Fechar ambiente


class CommandStatus(str, Enum):
    """Status do comando"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class IPCCommand:
    """Comando IPC"""
    command_id: str
    command_type: CommandType
    args: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command_id": self.command_id,
            "command_type": self.command_type.value,
            "args": self.args,
            "timestamp": self.timestamp
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IPCCommand':
        return cls(
            command_id=data["command_id"],
            command_type=CommandType(data["command_type"]),
            args=data.get("args", {}),
            timestamp=data.get("timestamp", datetime.now().isoformat())
        )


@dataclass
class IPCResponse:
    """Resposta IPC"""
    command_id: str
    status: CommandStatus
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command_id": self.command_id,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "timestamp": self.timestamp
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IPCResponse':
        return cls(
            command_id=data["command_id"],
            status=CommandStatus(data["status"]),
            result=data.get("result"),
            error=data.get("error"),
            timestamp=data.get("timestamp", datetime.now().isoformat())
        )


class SimulationIPCClient:
    """
    Cliente IPC para simulação (usado pelo lado Flask)

    Envia comandos ao processo de simulação e aguarda respostas
    """

    def __init__(self, simulation_dir: str):
        """
        Inicializa o cliente IPC

        Args:
            simulation_dir: Diretório de dados da simulação
        """
        self.simulation_dir = simulation_dir
        self.commands_dir = os.path.join(simulation_dir, "ipc_commands")
        self.responses_dir = os.path.join(simulation_dir, "ipc_responses")

        # Garante que os diretórios existam
        os.makedirs(self.commands_dir, exist_ok=True)
        os.makedirs(self.responses_dir, exist_ok=True)

    def send_command(
        self,
        command_type: CommandType,
        args: Dict[str, Any],
        timeout: float = 60.0,
        poll_interval: float = 0.5
    ) -> IPCResponse:
        """
        Envia comando e aguarda resposta

        Args:
            command_type: Tipo de comando
            args: Parâmetros do comando
            timeout: Tempo limite (segundos)
            poll_interval: Intervalo de polling (segundos)

        Returns:
            IPCResponse

        Raises:
            TimeoutError: Timeout ao aguardar resposta
        """
        command_id = str(uuid.uuid4())
        command = IPCCommand(
            command_id=command_id,
            command_type=command_type,
            args=args
        )

        # Escreve arquivo de comando
        command_file = os.path.join(self.commands_dir, f"{command_id}.json")
        with open(command_file, 'w', encoding='utf-8') as f:
            json.dump(command.to_dict(), f, ensure_ascii=False, indent=2)

        logger.info(f"Comando IPC enviado: {command_type.value}, command_id={command_id}")

        # Aguarda resposta
        response_file = os.path.join(self.responses_dir, f"{command_id}.json")
        start_time = time.time()

        while time.time() - start_time < timeout:
            if os.path.exists(response_file):
                try:
                    with open(response_file, 'r', encoding='utf-8') as f:
                        response_data = json.load(f)
                    response = IPCResponse.from_dict(response_data)

                    # Limpa arquivos de comando e resposta
                    try:
                        os.remove(command_file)
                        os.remove(response_file)
                    except OSError:
                        pass

                    logger.info(f"Resposta IPC recebida: command_id={command_id}, status={response.status.value}")
                    return response
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(f"Falha ao parsear resposta: {e}")

            time.sleep(poll_interval)

        # Timeout
        logger.error(f"Timeout ao aguardar resposta IPC: command_id={command_id}")

        # Limpa arquivo de comando
        try:
            os.remove(command_file)
        except OSError:
            pass

        raise TimeoutError(f"Timeout ao aguardar resposta do comando ({timeout}s)")

    def send_interview(
        self,
        agent_id: int,
        prompt: str,
        platform: str = None,
        timeout: float = 60.0
    ) -> IPCResponse:
        """
        Envia comando de entrevista para um único Agent

        Args:
            agent_id: ID do Agent
            prompt: Pergunta da entrevista
            platform: Plataforma específica (opcional)
                - "twitter": Entrevistar apenas na plataforma Twitter
                - "reddit": Entrevistar apenas na plataforma Reddit
                - None: Em simulação de duas plataformas, entrevista em ambas; em plataforma única, entrevista nessa plataforma
            timeout: Tempo limite

        Returns:
            IPCResponse, campo result contém o resultado da entrevista
        """
        args = {
            "agent_id": agent_id,
            "prompt": prompt
        }
        if platform:
            args["platform"] = platform

        return self.send_command(
            command_type=CommandType.INTERVIEW,
            args=args,
            timeout=timeout
        )

    def send_batch_interview(
        self,
        interviews: List[Dict[str, Any]],
        platform: str = None,
        timeout: float = 120.0
    ) -> IPCResponse:
        """
        Envia comando de entrevista em lote

        Args:
            interviews: Lista de entrevistas, cada elemento contém {"agent_id": int, "prompt": str, "platform": str(opcional)}
            platform: Plataforma padrão (opcional, será sobrescrita pelo platform de cada item da entrevista)
                - "twitter": Por padrão, entrevistar apenas na plataforma Twitter
                - "reddit": Por padrão, entrevistar apenas na plataforma Reddit
                - None: Em simulação de duas plataformas, cada Agent é entrevistado em ambas
            timeout: Tempo limite

        Returns:
            IPCResponse, campo result contém todos os resultados das entrevistas
        """
        args = {"interviews": interviews}
        if platform:
            args["platform"] = platform

        return self.send_command(
            command_type=CommandType.BATCH_INTERVIEW,
            args=args,
            timeout=timeout
        )

    def send_close_env(self, timeout: float = 30.0) -> IPCResponse:
        """
        Envia comando para fechar o ambiente

        Args:
            timeout: Tempo limite

        Returns:
            IPCResponse
        """
        return self.send_command(
            command_type=CommandType.CLOSE_ENV,
            args={},
            timeout=timeout
        )

    def check_env_alive(self) -> bool:
        """
        Verifica se o ambiente de simulação está ativo

        Verifica através do arquivo env_status.json
        """
        status_file = os.path.join(self.simulation_dir, "env_status.json")
        if not os.path.exists(status_file):
            return False

        try:
            with open(status_file, 'r', encoding='utf-8') as f:
                status = json.load(f)
            return status.get("status") == "alive"
        except (json.JSONDecodeError, OSError):
            return False


class SimulationIPCServer:
    """
    Servidor IPC para simulação (usado pelo lado do script de simulação)

    Faz polling no diretório de comandos, executa e retorna respostas
    """

    def __init__(self, simulation_dir: str):
        """
        Inicializa o servidor IPC

        Args:
            simulation_dir: Diretório de dados da simulação
        """
        self.simulation_dir = simulation_dir
        self.commands_dir = os.path.join(simulation_dir, "ipc_commands")
        self.responses_dir = os.path.join(simulation_dir, "ipc_responses")

        # Garante que os diretórios existam
        os.makedirs(self.commands_dir, exist_ok=True)
        os.makedirs(self.responses_dir, exist_ok=True)

        # Status do ambiente
        self._running = False

    def start(self):
        """Marca o servidor como em execução"""
        self._running = True
        self._update_env_status("alive")

    def stop(self):
        """Marca o servidor como parado"""
        self._running = False
        self._update_env_status("stopped")

    def _update_env_status(self, status: str):
        """Atualiza o arquivo de status do ambiente"""
        status_file = os.path.join(self.simulation_dir, "env_status.json")
        with open(status_file, 'w', encoding='utf-8') as f:
            json.dump({
                "status": status,
                "timestamp": datetime.now().isoformat()
            }, f, ensure_ascii=False, indent=2)

    def poll_commands(self) -> Optional[IPCCommand]:
        """
        Faz polling no diretório de comandos, retorna o primeiro comando pendente

        Returns:
            IPCCommand ou None
        """
        if not os.path.exists(self.commands_dir):
            return None

        # Obtém arquivos de comando ordenados por tempo
        command_files = []
        for filename in os.listdir(self.commands_dir):
            if filename.endswith('.json'):
                filepath = os.path.join(self.commands_dir, filename)
                command_files.append((filepath, os.path.getmtime(filepath)))

        command_files.sort(key=lambda x: x[1])

        for filepath, _ in command_files:
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return IPCCommand.from_dict(data)
            except (json.JSONDecodeError, KeyError, OSError) as e:
                logger.warning(f"Falha ao ler arquivo de comando: {filepath}, {e}")
                continue

        return None

    def send_response(self, response: IPCResponse):
        """
        Envia resposta

        Args:
            response: Resposta IPC
        """
        response_file = os.path.join(self.responses_dir, f"{response.command_id}.json")
        with open(response_file, 'w', encoding='utf-8') as f:
            json.dump(response.to_dict(), f, ensure_ascii=False, indent=2)

        # Remove arquivo de comando
        command_file = os.path.join(self.commands_dir, f"{response.command_id}.json")
        try:
            os.remove(command_file)
        except OSError:
            pass

    def send_success(self, command_id: str, result: Dict[str, Any]):
        """Envia resposta de sucesso"""
        self.send_response(IPCResponse(
            command_id=command_id,
            status=CommandStatus.COMPLETED,
            result=result
        ))

    def send_error(self, command_id: str, error: str):
        """Envia resposta de erro"""
        self.send_response(IPCResponse(
            command_id=command_id,
            status=CommandStatus.FAILED,
            error=error
        ))
