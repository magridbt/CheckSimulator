"""
Rotas da API de Simulação
Step2: Leitura e filtragem de entidades Zep, preparacao e execucao de simulacao OASIS (totalmente automatizado)
"""

import os
import traceback
from flask import request, jsonify, send_file

from . import simulation_bp
from ..config import Config
from ..services.zep_entity_reader import ZepEntityReader
from ..services.oasis_profile_generator import OasisProfileGenerator
from ..services.simulation_manager import SimulationManager, SimulationStatus
from ..services.simulation_runner import SimulationRunner, RunnerStatus
from ..utils.logger import get_logger
from ..models.project import ProjectManager

logger = get_logger('checksimulator.api.simulation')


# Prefixo de otimizacao do prompt de Interview
# Adicionar este prefixo evita que o Agent chame ferramentas, respondendo diretamente com texto
INTERVIEW_PROMPT_PREFIX = "结合你的人设、所有的过往记忆与行动，不调用任何工具直接用文本回复我："


def optimize_interview_prompt(prompt: str) -> str:
    """
    Otimizar pergunta de Interview, adicionando prefixo para evitar que o Agent chame ferramentas

    Args:
        prompt: Pergunta original

    Returns:
        Pergunta otimizada
    """
    if not prompt:
        return prompt
    # Evitar adicionar prefixo duplicado
    if prompt.startswith(INTERVIEW_PROMPT_PREFIX):
        return prompt
    return f"{INTERVIEW_PROMPT_PREFIX}{prompt}"


# ============== Interface de leitura de entidades ==============

@simulation_bp.route('/entities/<graph_id>', methods=['GET'])
def get_graph_entities(graph_id: str):
    """
    Obter todas as entidades do grafo (filtradas)

    Retorna apenas nos que correspondem a tipos de entidade predefinidos (nos cujos Labels nao sao apenas Entity)

    Parâmetros Query:
        entity_types: Lista de tipos de entidade separados por virgula (opcional, para filtragem adicional)
        enrich: Se deve obter informacoes de arestas relacionadas (padrao true)
    """
    try:
        if not Config.ZEP_API_KEY:
            return jsonify({
                "success": False,
                "error": "ZEP_API_KEY nao configurada"
            }), 500

        entity_types_str = request.args.get('entity_types', '')
        entity_types = [t.strip() for t in entity_types_str.split(',') if t.strip()] if entity_types_str else None
        enrich = request.args.get('enrich', 'true').lower() == 'true'

        logger.info(f"Obtendo entidades do grafo: graph_id={graph_id}, entity_types={entity_types}, enrich={enrich}")

        reader = ZepEntityReader()
        result = reader.filter_defined_entities(
            graph_id=graph_id,
            defined_entity_types=entity_types,
            enrich_with_edges=enrich
        )

        return jsonify({
            "success": True,
            "data": result.to_dict()
        })

    except Exception as e:
        logger.error(f"Falha ao obter entidades do grafo: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/entities/<graph_id>/<entity_uuid>', methods=['GET'])
def get_entity_detail(graph_id: str, entity_uuid: str):
    """Obter informacoes detalhadas de uma unica entidade"""
    try:
        if not Config.ZEP_API_KEY:
            return jsonify({
                "success": False,
                "error": "ZEP_API_KEY nao configurada"
            }), 500

        reader = ZepEntityReader()
        entity = reader.get_entity_with_context(graph_id, entity_uuid)

        if not entity:
            return jsonify({
                "success": False,
                "error": f"Entidade não encontrada: {entity_uuid}"
            }), 404

        return jsonify({
            "success": True,
            "data": entity.to_dict()
        })

    except Exception as e:
        logger.error(f"Falha ao obter detalhes da entidade: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/entities/<graph_id>/by-type/<entity_type>', methods=['GET'])
def get_entities_by_type(graph_id: str, entity_type: str):
    """Obter todas as entidades de um tipo especifico"""
    try:
        if not Config.ZEP_API_KEY:
            return jsonify({
                "success": False,
                "error": "ZEP_API_KEY nao configurada"
            }), 500

        enrich = request.args.get('enrich', 'true').lower() == 'true'

        reader = ZepEntityReader()
        entities = reader.get_entities_by_type(
            graph_id=graph_id,
            entity_type=entity_type,
            enrich_with_edges=enrich
        )

        return jsonify({
            "success": True,
            "data": {
                "entity_type": entity_type,
                "count": len(entities),
                "entities": [e.to_dict() for e in entities]
            }
        })

    except Exception as e:
        logger.error(f"Falha ao obter entidades: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Interface de gerenciamento de simulação ==============

@simulation_bp.route('/create', methods=['POST'])
def create_simulation():
    """
    Criar nova simulacao

    Nota: Parâmetros como max_rounds sao gerados inteligentemente pelo LLM, sem necessidade de configuracao manual

    Requisicao (JSON):
        {
            "project_id": "proj_xxxx",      // Obrigatorio
            "graph_id": "checksimulator_xxxx",    // Opcional, se nao fornecido, obtem do projeto
            "enable_twitter": true,          // Opcional, padrao true
            "enable_reddit": true            // Opcional, padrao true
        }

    Retorno:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "project_id": "proj_xxxx",
                "graph_id": "checksimulator_xxxx",
                "status": "created",
                "enable_twitter": true,
                "enable_reddit": true,
                "created_at": "2025-12-01T10:00:00"
            }
        }
    """
    try:
        data = request.get_json() or {}

        project_id = data.get('project_id')
        if not project_id:
            return jsonify({
                "success": False,
                "error": "Por favor, forneca o project_id"
            }), 400

        project = ProjectManager.get_project(project_id)
        if not project:
            return jsonify({
                "success": False,
                "error": f"Projeto não encontrado: {project_id}"
            }), 404

        graph_id = data.get('graph_id') or project.graph_id
        if not graph_id:
            return jsonify({
                "success": False,
                "error": "O projeto ainda nao construiu o grafo, por favor chame /api/graph/build primeiro"
            }), 400

        manager = SimulationManager()
        state = manager.create_simulation(
            project_id=project_id,
            graph_id=graph_id,
            enable_twitter=data.get('enable_twitter', True),
            enable_reddit=data.get('enable_reddit', True),
        )

        return jsonify({
            "success": True,
            "data": state.to_dict()
        })

    except Exception as e:
        logger.error(f"Falha ao criar simulação: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


def _check_simulation_prepared(simulation_id: str) -> tuple:
    """
    Verificar se a simulacao ja foi preparada

    Condicoes de verificacao:
    1. state.json existe e status e "ready"
    2. Arquivos necessarios existem: reddit_profiles.json, twitter_profiles.csv, simulation_config.json

    Nota: Scripts de execucao (run_*.py) permanecem em backend/scripts/, nao sao mais copiados para o diretorio de simulacao

    Args:
        simulation_id: ID da simulacao

    Returns:
        (is_prepared: bool, info: dict)
    """
    import os
    from ..config import Config

    simulation_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)

    # Verificar se o diretorio existe
    if not os.path.exists(simulation_dir):
        return False, {"reason": "Diretorio de simulacao nao existe"}

    # Lista de arquivos necessarios (nao inclui scripts, scripts estao em backend/scripts/)
    required_files = [
        "state.json",
        "simulation_config.json",
        "reddit_profiles.json",
        "twitter_profiles.csv"
    ]

    # Verificar se os arquivos existem
    existing_files = []
    missing_files = []
    for f in required_files:
        file_path = os.path.join(simulation_dir, f)
        if os.path.exists(file_path):
            existing_files.append(f)
        else:
            missing_files.append(f)

    if missing_files:
        return False, {
            "reason": "Arquivos necessarios ausentes",
            "missing_files": missing_files,
            "existing_files": existing_files
        }

    # Verificar status no state.json
    state_file = os.path.join(simulation_dir, "state.json")
    try:
        import json
        with open(state_file, 'r', encoding='utf-8') as f:
            state_data = json.load(f)

        status = state_data.get("status", "")
        config_generated = state_data.get("config_generated", False)

        # Log detalhado
        logger.debug(f"Detectando estado de preparacao da simulacao: {simulation_id}, status={status}, config_generated={config_generated}")

        # Se config_generated=True e arquivos existem, considerar preparacao concluida
        # Os seguintes status indicam que a preparacao foi concluida:
        # - ready: Preparacao concluida, pronto para executar
        # - preparing: Se config_generated=True indica que ja foi concluido
        # - running: Em execucao, indica que a preparacao ja foi concluida ha tempo
        # - completed: Execucao concluida, indica que a preparacao ja foi concluida ha tempo
        # - stopped: Parado, indica que a preparacao ja foi concluida ha tempo
        # - failed: Execucao falhou (mas a preparacao foi concluida)
        prepared_statuses = ["ready", "preparing", "running", "completed", "stopped", "failed"]
        if status in prepared_statuses and config_generated:
            # Obter informacoes estatisticas dos arquivos
            profiles_file = os.path.join(simulation_dir, "reddit_profiles.json")
            config_file = os.path.join(simulation_dir, "simulation_config.json")

            profiles_count = 0
            if os.path.exists(profiles_file):
                with open(profiles_file, 'r', encoding='utf-8') as f:
                    profiles_data = json.load(f)
                    profiles_count = len(profiles_data) if isinstance(profiles_data, list) else 0

            # Se o status e preparing mas os arquivos estao completos, atualizar automaticamente para ready
            if status == "preparing":
                try:
                    state_data["status"] = "ready"
                    from datetime import datetime
                    state_data["updated_at"] = datetime.now().isoformat()
                    with open(state_file, 'w', encoding='utf-8') as f:
                        json.dump(state_data, f, ensure_ascii=False, indent=2)
                    logger.info(f"Status da simulacao atualizado automaticamente: {simulation_id} preparing -> ready")
                    status = "ready"
                except Exception as e:
                    logger.warning(f"Falha ao atualizar status automaticamente: {e}")

            logger.info(f"Simulacao {simulation_id} resultado da verificacao: preparacao concluida (status={status}, config_generated={config_generated})")
            return True, {
                "status": status,
                "entities_count": state_data.get("entities_count", 0),
                "profiles_count": profiles_count,
                "entity_types": state_data.get("entity_types", []),
                "config_generated": config_generated,
                "created_at": state_data.get("created_at"),
                "updated_at": state_data.get("updated_at"),
                "existing_files": existing_files
            }
        else:
            logger.warning(f"Simulacao {simulation_id} resultado da verificacao: preparacao nao concluida (status={status}, config_generated={config_generated})")
            return False, {
                "reason": f"Status nao esta na lista de preparados ou config_generated e false: status={status}, config_generated={config_generated}",
                "status": status,
                "config_generated": config_generated
            }

    except Exception as e:
        return False, {"reason": f"Falha ao ler arquivo de estado: {str(e)}"}


@simulation_bp.route('/prepare', methods=['POST'])
def prepare_simulation():
    """
    Preparar ambiente de simulação (tarefa assincrona, LLM gera todos os parametros inteligentemente)

    Esta e uma operacao demorada, a interface retorna imediatamente o task_id,
    use GET /api/simulation/prepare/status para consultar o progresso

    Recursos:
    - Detecta automaticamente trabalho de preparacao ja concluido, evitando geracao duplicada
    - Se ja preparado, retorna diretamente os resultados existentes
    - Suporta regeneracao forcada (force_regenerate=true)

    Passos:
    1. Verificar se ja existe trabalho de preparacao concluido
    2. Ler e filtrar entidades do grafo Zep
    3. Gerar OASIS Agent Profile para cada entidade (com mecanismo de retry)
    4. LLM gera configuracao de simulacao inteligentemente (com mecanismo de retry)
    5. Salvar arquivos de configuracao e scripts predefinidos

    Requisicao (JSON):
        {
            "simulation_id": "sim_xxxx",                   // Obrigatorio, ID da simulacao
            "entity_types": ["Student", "PublicFigure"],  // Opcional, especificar tipos de entidade
            "use_llm_for_profiles": true,                 // Opcional, usar LLM para gerar perfis
            "parallel_profile_count": 5,                  // Opcional, quantidade de perfis gerados em paralelo, padrao 5
            "force_regenerate": false                     // Opcional, forcar regeneracao, padrao false
        }

    Retorno:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "task_id": "task_xxxx",           // Retornado para nova tarefa
                "status": "preparing|ready",
                "message": "Tarefa de preparacao iniciada|Trabalho de preparacao ja concluido",
                "already_prepared": true|false    // Se ja esta preparado
            }
        }
    """
    import threading
    import os
    from ..models.task import TaskManager, TaskStatus
    from ..config import Config

    try:
        data = request.get_json() or {}

        simulation_id = data.get('simulation_id')
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "Por favor, forneca o simulation_id"
            }), 400

        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)

        if not state:
            return jsonify({
                "success": False,
                "error": f"Simulacao não encontrada: {simulation_id}"
            }), 404

        # Verificar se e regeneracao forcada
        force_regenerate = data.get('force_regenerate', False)
        logger.info(f"Iniciando processamento da requisicao /prepare: simulation_id={simulation_id}, force_regenerate={force_regenerate}")

        # Verificar se ja esta preparado (evitar geracao duplicada)
        if not force_regenerate:
            logger.debug(f"Verificando se a simulacao {simulation_id} ja esta preparada...")
            is_prepared, prepare_info = _check_simulation_prepared(simulation_id)
            logger.debug(f"Resultado da verificacao: is_prepared={is_prepared}, prepare_info={prepare_info}")
            if is_prepared:
                logger.info(f"Simulacao {simulation_id} ja esta preparada, ignorando geracao duplicada")
                return jsonify({
                    "success": True,
                    "data": {
                        "simulation_id": simulation_id,
                        "status": "ready",
                        "message": "Trabalho de preparacao ja concluido, sem necessidade de regenerar",
                        "already_prepared": True,
                        "prepare_info": prepare_info
                    }
                })
            else:
                logger.info(f"Simulacao {simulation_id} nao esta preparada, iniciando tarefa de preparacao")

        # Obter informacoes necessarias do projeto
        project = ProjectManager.get_project(state.project_id)
        if not project:
            return jsonify({
                "success": False,
                "error": f"Projeto não encontrado: {state.project_id}"
            }), 404

        # Obter requisito de simulacao
        simulation_requirement = project.simulation_requirement or ""
        if not simulation_requirement:
            return jsonify({
                "success": False,
                "error": "O projeto esta sem descricao do requisito de simulacao (simulation_requirement)"
            }), 400

        # Obter texto do documento
        document_text = ProjectManager.get_extracted_text(state.project_id) or ""

        entity_types_list = data.get('entity_types')
        use_llm_for_profiles = data.get('use_llm_for_profiles', True)
        parallel_profile_count = data.get('parallel_profile_count', 5)

        # ========== Obter quantidade de entidades sincronamente (antes de iniciar a tarefa em segundo plano) ==========
        # Assim o frontend pode obter o total esperado de Agents imediatamente apos chamar prepare
        try:
            logger.info(f"Obtendo quantidade de entidades sincronamente: graph_id={state.graph_id}")
            reader = ZepEntityReader()
            # Leitura rapida de entidades (sem informacoes de arestas, apenas contagem)
            filtered_preview = reader.filter_defined_entities(
                graph_id=state.graph_id,
                defined_entity_types=entity_types_list,
                enrich_with_edges=False  # Nao obter informacoes de arestas, acelerar
            )
            # Salvar quantidade de entidades no estado (para o frontend obter imediatamente)
            state.entities_count = filtered_preview.filtered_count
            state.entity_types = list(filtered_preview.entity_types)
            logger.info(f"Quantidade esperada de entidades: {filtered_preview.filtered_count}, tipos: {filtered_preview.entity_types}")
        except Exception as e:
            logger.warning(f"Falha ao obter quantidade de entidades sincronamente (sera tentado novamente na tarefa em segundo plano): {e}")
            # Falha nao afeta o fluxo seguinte, tarefa em segundo plano vai obter novamente

        # Criar tarefa assincrona
        task_manager = TaskManager()
        task_id = task_manager.create_task(
            task_type="simulation_prepare",
            metadata={
                "simulation_id": simulation_id,
                "project_id": state.project_id
            }
        )

        # Atualizar estado da simulacao (incluindo quantidade de entidades obtida previamente)
        state.status = SimulationStatus.PREPARING
        manager._save_simulation_state(state)

        # Definir tarefa em segundo plano
        def run_prepare():
            try:
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.PROCESSING,
                    progress=0,
                    message="Iniciando preparacao do ambiente de simulacao..."
                )

                # Preparar simulacao (com callback de progresso)
                # Armazenar detalhes de progresso por etapa
                stage_details = {}

                def progress_callback(stage, progress, message, **kwargs):
                    # Calcular progresso total
                    stage_weights = {
                        "reading": (0, 20),           # 0-20%
                        "generating_profiles": (20, 70),  # 20-70%
                        "generating_config": (70, 90),    # 70-90%
                        "copying_scripts": (90, 100)       # 90-100%
                    }

                    start, end = stage_weights.get(stage, (0, 100))
                    current_progress = int(start + (end - start) * progress / 100)

                    # Construir informacoes detalhadas de progresso
                    stage_names = {
                        "reading": "Lendo entidades do grafo",
                        "generating_profiles": "Gerando perfis de Agent",
                        "generating_config": "Gerando configuracao de simulacao",
                        "copying_scripts": "Preparando scripts de simulacao"
                    }

                    stage_index = list(stage_weights.keys()).index(stage) + 1 if stage in stage_weights else 1
                    total_stages = len(stage_weights)

                    # Atualizar detalhes da etapa
                    stage_details[stage] = {
                        "stage_name": stage_names.get(stage, stage),
                        "stage_progress": progress,
                        "current": kwargs.get("current", 0),
                        "total": kwargs.get("total", 0),
                        "item_name": kwargs.get("item_name", "")
                    }

                    # Construir informacoes detalhadas de progresso
                    detail = stage_details[stage]
                    progress_detail_data = {
                        "current_stage": stage,
                        "current_stage_name": stage_names.get(stage, stage),
                        "stage_index": stage_index,
                        "total_stages": total_stages,
                        "stage_progress": progress,
                        "current_item": detail["current"],
                        "total_items": detail["total"],
                        "item_description": message
                    }

                    # Construir mensagem concisa
                    if detail["total"] > 0:
                        detailed_message = (
                            f"[{stage_index}/{total_stages}] {stage_names.get(stage, stage)}: "
                            f"{detail['current']}/{detail['total']} - {message}"
                        )
                    else:
                        detailed_message = f"[{stage_index}/{total_stages}] {stage_names.get(stage, stage)}: {message}"

                    task_manager.update_task(
                        task_id,
                        progress=current_progress,
                        message=detailed_message,
                        progress_detail=progress_detail_data
                    )

                result_state = manager.prepare_simulation(
                    simulation_id=simulation_id,
                    simulation_requirement=simulation_requirement,
                    document_text=document_text,
                    defined_entity_types=entity_types_list,
                    use_llm_for_profiles=use_llm_for_profiles,
                    progress_callback=progress_callback,
                    parallel_profile_count=parallel_profile_count
                )

                # Tarefa concluida
                task_manager.complete_task(
                    task_id,
                    result=result_state.to_simple_dict()
                )

            except Exception as e:
                logger.error(f"Falha ao preparar simulacao: {str(e)}")
                task_manager.fail_task(task_id, str(e))

                # Atualizar estado da simulacao para falha
                state = manager.get_simulation(simulation_id)
                if state:
                    state.status = SimulationStatus.FAILED
                    state.error = str(e)
                    manager._save_simulation_state(state)

        # Iniciar thread em segundo plano
        thread = threading.Thread(target=run_prepare, daemon=True)
        thread.start()

        return jsonify({
            "success": True,
            "data": {
                "simulation_id": simulation_id,
                "task_id": task_id,
                "status": "preparing",
                "message": "Tarefa de preparacao iniciada, consulte o progresso via /api/simulation/prepare/status",
                "already_prepared": False,
                "expected_entities_count": state.entities_count,  # Total esperado de Agents
                "entity_types": state.entity_types  # Lista de tipos de entidade
            }
        })

    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 404

    except Exception as e:
        logger.error(f"Falha ao iniciar tarefa de preparacao: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/prepare/status', methods=['POST'])
def get_prepare_status():
    """
    Consultar progresso da tarefa de preparacao

    Suporta duas formas de consulta:
    1. Consultar progresso de tarefa em andamento via task_id
    2. Verificar se ja existe trabalho de preparacao concluido via simulation_id

    Requisicao (JSON):
        {
            "task_id": "task_xxxx",          // Opcional, task_id retornado pelo prepare
            "simulation_id": "sim_xxxx"      // Opcional, ID da simulacao (para verificar preparacao concluida)
        }

    Retorno:
        {
            "success": true,
            "data": {
                "task_id": "task_xxxx",
                "status": "processing|completed|ready",
                "progress": 45,
                "message": "...",
                "already_prepared": true|false,  // Se ja existe preparacao concluida
                "prepare_info": {...}            // Informacoes detalhadas quando preparacao concluida
            }
        }
    """
    from ..models.task import TaskManager

    try:
        data = request.get_json() or {}

        task_id = data.get('task_id')
        simulation_id = data.get('simulation_id')

        # Se simulation_id fornecido, verificar primeiro se ja esta preparado
        if simulation_id:
            is_prepared, prepare_info = _check_simulation_prepared(simulation_id)
            if is_prepared:
                return jsonify({
                    "success": True,
                    "data": {
                        "simulation_id": simulation_id,
                        "status": "ready",
                        "progress": 100,
                        "message": "Trabalho de preparacao ja concluido",
                        "already_prepared": True,
                        "prepare_info": prepare_info
                    }
                })

        # Se nao tem task_id, retornar erro
        if not task_id:
            if simulation_id:
                # Tem simulation_id mas nao esta preparado
                return jsonify({
                    "success": True,
                    "data": {
                        "simulation_id": simulation_id,
                        "status": "not_started",
                        "progress": 0,
                        "message": "Preparacao ainda nao iniciada, por favor chame /api/simulation/prepare para iniciar",
                        "already_prepared": False
                    }
                })
            return jsonify({
                "success": False,
                "error": "Por favor, forneca task_id ou simulation_id"
            }), 400

        task_manager = TaskManager()
        task = task_manager.get_task(task_id)

        if not task:
            # Tarefa nao existe, mas se tem simulation_id, verificar se ja esta preparado
            if simulation_id:
                is_prepared, prepare_info = _check_simulation_prepared(simulation_id)
                if is_prepared:
                    return jsonify({
                        "success": True,
                        "data": {
                            "simulation_id": simulation_id,
                            "task_id": task_id,
                            "status": "ready",
                            "progress": 100,
                            "message": "Tarefa concluida (trabalho de preparacao ja existe)",
                            "already_prepared": True,
                            "prepare_info": prepare_info
                        }
                    })

            return jsonify({
                "success": False,
                "error": f"Tarefa não encontrada: {task_id}"
            }), 404

        task_dict = task.to_dict()
        task_dict["already_prepared"] = False

        return jsonify({
            "success": True,
            "data": task_dict
        })

    except Exception as e:
        logger.error(f"Falha ao consultar estado da tarefa: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@simulation_bp.route('/<simulation_id>', methods=['GET'])
def get_simulation(simulation_id: str):
    """Obter estado da simulacao"""
    try:
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)

        if not state:
            return jsonify({
                "success": False,
                "error": f"Simulacao não encontrada: {simulation_id}"
            }), 404

        result = state.to_dict()

        # Se a simulacao esta pronta, anexar instrucoes de execucao
        if state.status == SimulationStatus.READY:
            result["run_instructions"] = manager.get_run_instructions(simulation_id)

        return jsonify({
            "success": True,
            "data": result
        })

    except Exception as e:
        logger.error(f"Falha ao obter estado da simulacao: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/list', methods=['GET'])
def list_simulations():
    """
    Listar todas as simulacoes

    Parâmetros Query:
        project_id: Filtrar por ID do projeto (opcional)
    """
    try:
        project_id = request.args.get('project_id')

        manager = SimulationManager()
        simulations = manager.list_simulations(project_id=project_id)

        return jsonify({
            "success": True,
            "data": [s.to_dict() for s in simulations],
            "count": len(simulations)
        })

    except Exception as e:
        logger.error(f"Falha ao listar simulacoes: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


def _get_report_id_for_simulation(simulation_id: str) -> str:
    """
    Obter o report_id mais recente correspondente a simulacao

    Percorre o diretorio de reports, encontra o report com simulation_id correspondente,
    se houver multiplos retorna o mais recente (ordenado por created_at)

    Args:
        simulation_id: ID da simulacao

    Returns:
        report_id ou None
    """
    import json
    from datetime import datetime

    # Caminho do diretorio de reports: backend/uploads/reports
    # __file__ e app/api/simulation.py, precisa subir dois niveis ate backend/
    reports_dir = os.path.join(os.path.dirname(__file__), '../../uploads/reports')
    if not os.path.exists(reports_dir):
        return None

    matching_reports = []

    try:
        for report_folder in os.listdir(reports_dir):
            report_path = os.path.join(reports_dir, report_folder)
            if not os.path.isdir(report_path):
                continue

            meta_file = os.path.join(report_path, "meta.json")
            if not os.path.exists(meta_file):
                continue

            try:
                with open(meta_file, 'r', encoding='utf-8') as f:
                    meta = json.load(f)

                if meta.get("simulation_id") == simulation_id:
                    matching_reports.append({
                        "report_id": meta.get("report_id"),
                        "created_at": meta.get("created_at", ""),
                        "status": meta.get("status", "")
                    })
            except Exception:
                continue

        if not matching_reports:
            return None

        # Ordenar por data de criacao decrescente, retornar o mais recente
        matching_reports.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return matching_reports[0].get("report_id")

    except Exception as e:
        logger.warning(f"Falha ao buscar report da simulacao {simulation_id}: {e}")
        return None


@simulation_bp.route('/history', methods=['GET'])
def get_simulation_history():
    """
    Obter lista de simulacoes historicas (com detalhes do projeto)

    Usado para exibir projetos historicos na pagina inicial, retorna lista de simulacoes com informacoes ricas como nome do projeto, descricao etc.

    Parâmetros Query:
        limit: Limite de quantidade retornada (padrao 20)

    Retorno:
        {
            "success": true,
            "data": [
                {
                    "simulation_id": "sim_xxxx",
                    "project_id": "proj_xxxx",
                    "project_name": "Analise de opiniao publica",
                    "simulation_requirement": "Se a universidade publicar...",
                    "status": "completed",
                    "entities_count": 68,
                    "profiles_count": 68,
                    "entity_types": ["Student", "Professor", ...],
                    "created_at": "2024-12-10",
                    "updated_at": "2024-12-10",
                    "total_rounds": 120,
                    "current_round": 120,
                    "report_id": "report_xxxx",
                    "version": "v1.0.2"
                },
                ...
            ],
            "count": 7
        }
    """
    try:
        limit = request.args.get('limit', 20, type=int)

        manager = SimulationManager()
        simulations = manager.list_simulations()[:limit]

        # Enriquecer dados da simulacao, lendo apenas dos arquivos de Simulacao
        enriched_simulations = []
        for sim in simulations:
            sim_dict = sim.to_dict()

            # Obter informacoes de configuracao da simulacao (ler simulation_requirement do simulation_config.json)
            config = manager.get_simulation_config(sim.simulation_id)
            if config:
                sim_dict["simulation_requirement"] = config.get("simulation_requirement", "")
                time_config = config.get("time_config", {})
                sim_dict["total_simulation_hours"] = time_config.get("total_simulation_hours", 0)
                # Rounds recomendados (valor de fallback)
                recommended_rounds = int(
                    time_config.get("total_simulation_hours", 0) * 60 /
                    max(time_config.get("minutes_per_round", 60), 1)
                )
            else:
                sim_dict["simulation_requirement"] = ""
                sim_dict["total_simulation_hours"] = 0
                recommended_rounds = 0

            # Obter estado de execucao (ler total de rounds definido pelo usuario do run_state.json)
            run_state = SimulationRunner.get_run_state(sim.simulation_id)
            if run_state:
                sim_dict["current_round"] = run_state.current_round
                sim_dict["runner_status"] = run_state.runner_status.value
                # Usar total_rounds definido pelo usuario, se nao houver usar rounds recomendados
                sim_dict["total_rounds"] = run_state.total_rounds if run_state.total_rounds > 0 else recommended_rounds
            else:
                sim_dict["current_round"] = 0
                sim_dict["runner_status"] = "idle"
                sim_dict["total_rounds"] = recommended_rounds

            # Obter lista de arquivos do projeto associado (maximo 3)
            project = ProjectManager.get_project(sim.project_id)
            if project and hasattr(project, 'files') and project.files:
                sim_dict["files"] = [
                    {"filename": f.get("filename", "Arquivo desconhecido")}
                    for f in project.files[:3]
                ]
            else:
                sim_dict["files"] = []

            # Obter report_id associado (buscar o report mais recente dessa simulacao)
            sim_dict["report_id"] = _get_report_id_for_simulation(sim.simulation_id)

            # Adicionar numero de versao
            sim_dict["version"] = "v1.0.2"

            # Formatar data
            try:
                created_date = sim_dict.get("created_at", "")[:10]
                sim_dict["created_date"] = created_date
            except:
                sim_dict["created_date"] = ""

            enriched_simulations.append(sim_dict)

        return jsonify({
            "success": True,
            "data": enriched_simulations,
            "count": len(enriched_simulations)
        })

    except Exception as e:
        logger.error(f"Falha ao obter historico de simulacoes: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/profiles', methods=['GET'])
def get_simulation_profiles(simulation_id: str):
    """
    Obter Agent Profile da simulacao

    Parâmetros Query:
        platform: Tipo de plataforma (reddit/twitter, padrao reddit)
    """
    try:
        platform = request.args.get('platform', 'reddit')

        manager = SimulationManager()
        profiles = manager.get_profiles(simulation_id, platform=platform)

        return jsonify({
            "success": True,
            "data": {
                "platform": platform,
                "count": len(profiles),
                "profiles": profiles
            }
        })

    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 404

    except Exception as e:
        logger.error(f"Falha ao obter Profile: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/profiles/realtime', methods=['GET'])
def get_simulation_profiles_realtime(simulation_id: str):
    """
    Obter Agent Profile da simulacao em tempo real (para visualizar progresso durante a geracao)

    Diferenca em relacao a interface /profiles:
    - Le diretamente do arquivo, sem passar pelo SimulationManager
    - Adequado para visualizacao em tempo real durante a geracao
    - Retorna metadados adicionais (como horario de modificacao do arquivo, se esta gerando etc.)

    Parâmetros Query:
        platform: Tipo de plataforma (reddit/twitter, padrao reddit)

    Retorno:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "platform": "reddit",
                "count": 15,
                "total_expected": 93,  // Total esperado (se disponivel)
                "is_generating": true,  // Se esta gerando
                "file_exists": true,
                "file_modified_at": "2025-12-04T18:20:00",
                "profiles": [...]
            }
        }
    """
    import json
    import csv
    from datetime import datetime

    try:
        platform = request.args.get('platform', 'reddit')

        # Obter diretorio da simulacao
        sim_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)

        if not os.path.exists(sim_dir):
            return jsonify({
                "success": False,
                "error": f"Simulacao não encontrada: {simulation_id}"
            }), 404

        # Determinar caminho do arquivo
        if platform == "reddit":
            profiles_file = os.path.join(sim_dir, "reddit_profiles.json")
        else:
            profiles_file = os.path.join(sim_dir, "twitter_profiles.csv")

        # Verificar se o arquivo existe
        file_exists = os.path.exists(profiles_file)
        profiles = []
        file_modified_at = None

        if file_exists:
            # Obter horario de modificacao do arquivo
            file_stat = os.stat(profiles_file)
            file_modified_at = datetime.fromtimestamp(file_stat.st_mtime).isoformat()

            try:
                if platform == "reddit":
                    with open(profiles_file, 'r', encoding='utf-8') as f:
                        profiles = json.load(f)
                else:
                    with open(profiles_file, 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        profiles = list(reader)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Falha ao ler arquivo de profiles (pode estar sendo escrito): {e}")
                profiles = []

        # Verificar se esta gerando (via state.json)
        is_generating = False
        total_expected = None

        state_file = os.path.join(sim_dir, "state.json")
        if os.path.exists(state_file):
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    state_data = json.load(f)
                    status = state_data.get("status", "")
                    is_generating = status == "preparing"
                    total_expected = state_data.get("entities_count")
            except Exception:
                pass

        return jsonify({
            "success": True,
            "data": {
                "simulation_id": simulation_id,
                "platform": platform,
                "count": len(profiles),
                "total_expected": total_expected,
                "is_generating": is_generating,
                "file_exists": file_exists,
                "file_modified_at": file_modified_at,
                "profiles": profiles
            }
        })

    except Exception as e:
        logger.error(f"Falha ao obter Profile em tempo real: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/config/realtime', methods=['GET'])
def get_simulation_config_realtime(simulation_id: str):
    """
    Obter configuracao de simulacao em tempo real (para visualizar progresso durante a geracao)

    Diferenca em relacao a interface /config:
    - Le diretamente do arquivo, sem passar pelo SimulationManager
    - Adequado para visualizacao em tempo real durante a geracao
    - Retorna metadados adicionais (como horario de modificacao do arquivo, se esta gerando etc.)
    - Mesmo que a configuracao ainda nao tenha sido gerada completamente, pode retornar informacoes parciais

    Retorno:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "file_exists": true,
                "file_modified_at": "2025-12-04T18:20:00",
                "is_generating": true,  // Se esta gerando
                "generation_stage": "generating_config",  // Etapa atual de geracao
                "config": {...}  // Conteudo da configuracao (se existir)
            }
        }
    """
    import json
    from datetime import datetime

    try:
        # Obter diretorio da simulacao
        sim_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)

        if not os.path.exists(sim_dir):
            return jsonify({
                "success": False,
                "error": f"Simulacao não encontrada: {simulation_id}"
            }), 404

        # Caminho do arquivo de configuracao
        config_file = os.path.join(sim_dir, "simulation_config.json")

        # Verificar se o arquivo existe
        file_exists = os.path.exists(config_file)
        config = None
        file_modified_at = None

        if file_exists:
            # Obter horario de modificacao do arquivo
            file_stat = os.stat(config_file)
            file_modified_at = datetime.fromtimestamp(file_stat.st_mtime).isoformat()

            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Falha ao ler arquivo de config (pode estar sendo escrito): {e}")
                config = None

        # Verificar se esta gerando (via state.json)
        is_generating = False
        generation_stage = None
        config_generated = False

        state_file = os.path.join(sim_dir, "state.json")
        if os.path.exists(state_file):
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    state_data = json.load(f)
                    status = state_data.get("status", "")
                    is_generating = status == "preparing"
                    config_generated = state_data.get("config_generated", False)

                    # Determinar etapa atual
                    if is_generating:
                        if state_data.get("profiles_generated", False):
                            generation_stage = "generating_config"
                        else:
                            generation_stage = "generating_profiles"
                    elif status == "ready":
                        generation_stage = "completed"
            except Exception:
                pass

        # Construir dados de resposta
        response_data = {
            "simulation_id": simulation_id,
            "file_exists": file_exists,
            "file_modified_at": file_modified_at,
            "is_generating": is_generating,
            "generation_stage": generation_stage,
            "config_generated": config_generated,
            "config": config
        }

        # Se a configuracao existe, extrair algumas estatisticas chave
        if config:
            response_data["summary"] = {
                "total_agents": len(config.get("agent_configs", [])),
                "simulation_hours": config.get("time_config", {}).get("total_simulation_hours"),
                "initial_posts_count": len(config.get("event_config", {}).get("initial_posts", [])),
                "hot_topics_count": len(config.get("event_config", {}).get("hot_topics", [])),
                "has_twitter_config": "twitter_config" in config,
                "has_reddit_config": "reddit_config" in config,
                "generated_at": config.get("generated_at"),
                "llm_model": config.get("llm_model")
            }

        return jsonify({
            "success": True,
            "data": response_data
        })

    except Exception as e:
        logger.error(f"Falha ao obter Config em tempo real: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/config', methods=['GET'])
def get_simulation_config(simulation_id: str):
    """
    Obter configuracao de simulacao (configuracao completa gerada inteligentemente pelo LLM)

    Retorna:
        - time_config: Configuracao de tempo (duracao da simulacao, rounds, periodos de pico/vale)
        - agent_configs: Configuracao de atividade de cada Agent (nivel de atividade, frequencia de fala, posicionamento etc.)
        - event_config: Configuracao de eventos (posts iniciais, topicos em alta)
        - platform_configs: Configuracao de plataformas
        - generation_reasoning: Explicacao do raciocinio de configuracao do LLM
    """
    try:
        manager = SimulationManager()
        config = manager.get_simulation_config(simulation_id)

        if not config:
            return jsonify({
                "success": False,
                "error": f"Configuracao de simulacao nao encontrada, por favor chame a interface /prepare primeiro"
            }), 404

        return jsonify({
            "success": True,
            "data": config
        })

    except Exception as e:
        logger.error(f"Falha ao obter configuracao: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/config/download', methods=['GET'])
def download_simulation_config(simulation_id: str):
    """Baixar arquivo de configuracao de simulacao"""
    try:
        manager = SimulationManager()
        sim_dir = manager._get_simulation_dir(simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")

        if not os.path.exists(config_path):
            return jsonify({
                "success": False,
                "error": "Arquivo de configuracao nao encontrado, por favor chame a interface /prepare primeiro"
            }), 404

        return send_file(
            config_path,
            as_attachment=True,
            download_name="simulation_config.json"
        )

    except Exception as e:
        logger.error(f"Falha ao baixar configuracao: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/script/<script_name>/download', methods=['GET'])
def download_simulation_script(script_name: str):
    """
    Baixar arquivo de script de execucao de simulacao (scripts gerais, localizados em backend/scripts/)

    script_name valores possiveis:
        - run_twitter_simulation.py
        - run_reddit_simulation.py
        - run_parallel_simulation.py
        - action_logger.py
    """
    try:
        # Scripts localizados no diretorio backend/scripts/
        scripts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../scripts'))

        # Validar nome do script
        allowed_scripts = [
            "run_twitter_simulation.py",
            "run_reddit_simulation.py",
            "run_parallel_simulation.py",
            "action_logger.py"
        ]

        if script_name not in allowed_scripts:
            return jsonify({
                "success": False,
                "error": f"Script desconhecido: {script_name}, opcoes: {allowed_scripts}"
            }), 400

        script_path = os.path.join(scripts_dir, script_name)

        if not os.path.exists(script_path):
            return jsonify({
                "success": False,
                "error": f"Arquivo de script nao encontrado: {script_name}"
            }), 404

        return send_file(
            script_path,
            as_attachment=True,
            download_name=script_name
        )

    except Exception as e:
        logger.error(f"Falha ao baixar script: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Interface de geracao de Profile (uso independente) ==============

@simulation_bp.route('/generate-profiles', methods=['POST'])
def generate_profiles():
    """
    Gerar OASIS Agent Profile diretamente do grafo (sem criar simulacao)

    Requisicao (JSON):
        {
            "graph_id": "checksimulator_xxxx",     // Obrigatorio
            "entity_types": ["Student"],      // Opcional
            "use_llm": true,                  // Opcional
            "platform": "reddit"              // Opcional
        }
    """
    try:
        data = request.get_json() or {}

        graph_id = data.get('graph_id')
        if not graph_id:
            return jsonify({
                "success": False,
                "error": "Por favor, forneca o graph_id"
            }), 400

        entity_types = data.get('entity_types')
        use_llm = data.get('use_llm', True)
        platform = data.get('platform', 'reddit')

        reader = ZepEntityReader()
        filtered = reader.filter_defined_entities(
            graph_id=graph_id,
            defined_entity_types=entity_types,
            enrich_with_edges=True
        )

        if filtered.filtered_count == 0:
            return jsonify({
                "success": False,
                "error": "Nenhuma entidade encontrada que atenda aos criterios"
            }), 400

        generator = OasisProfileGenerator()
        profiles = generator.generate_profiles_from_entities(
            entities=filtered.entities,
            use_llm=use_llm
        )

        if platform == "reddit":
            profiles_data = [p.to_reddit_format() for p in profiles]
        elif platform == "twitter":
            profiles_data = [p.to_twitter_format() for p in profiles]
        else:
            profiles_data = [p.to_dict() for p in profiles]

        return jsonify({
            "success": True,
            "data": {
                "platform": platform,
                "entity_types": list(filtered.entity_types),
                "count": len(profiles_data),
                "profiles": profiles_data
            }
        })

    except Exception as e:
        logger.error(f"Falha ao gerar Profile: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Interface de controle de execucao de simulacao ==============

@simulation_bp.route('/start', methods=['POST'])
def start_simulation():
    """
    Iniciar execucao de simulacao

    Requisicao (JSON):
        {
            "simulation_id": "sim_xxxx",          // Obrigatorio, ID da simulacao
            "platform": "parallel",                // Opcional: twitter / reddit / parallel (padrao)
            "max_rounds": 100,                     // Opcional: maximo de rounds de simulacao, para truncar simulacoes muito longas
            "enable_graph_memory_update": false,   // Opcional: se deve atualizar atividade do Agent na memoria do grafo Zep dinamicamente
            "force": false                         // Opcional: forcar reinicio (para a simulacao em execucao e limpa logs)
        }

    Sobre o parametro force:
        - Quando ativado, se a simulacao esta em execucao ou concluida, para e limpa os logs de execucao
        - Conteudo limpo inclui: run_state.json, actions.jsonl, simulation.log etc.
        - Nao limpa arquivos de configuracao (simulation_config.json) e arquivos de profile
        - Adequado para cenarios onde e necessario re-executar a simulacao

    Sobre enable_graph_memory_update:
        - Quando ativado, todas as atividades dos Agents na simulacao (posts, comentarios, curtidas etc.) sao atualizadas em tempo real no grafo Zep
        - Isso permite que o grafo "lembre" do processo de simulacao, para analise posterior ou conversa com IA
        - Requer que o projeto associado a simulacao tenha um graph_id valido
        - Utiliza mecanismo de atualizacao em lote, reduzindo chamadas de API

    Retorno:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "runner_status": "running",
                "process_pid": 12345,
                "twitter_running": true,
                "reddit_running": true,
                "started_at": "2025-12-01T10:00:00",
                "graph_memory_update_enabled": true,  // Se a atualizacao de memoria do grafo esta ativada
                "force_restarted": true               // Se foi reinicio forcado
            }
        }
    """
    try:
        data = request.get_json() or {}

        simulation_id = data.get('simulation_id')
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "Por favor, forneca o simulation_id"
            }), 400

        platform = data.get('platform', 'parallel')
        max_rounds = data.get('max_rounds')  # Opcional: maximo de rounds de simulacao
        enable_graph_memory_update = data.get('enable_graph_memory_update', False)  # Opcional: se deve ativar atualizacao de memoria do grafo
        force = data.get('force', False)  # Opcional: forcar reinicio

        # Validar parametro max_rounds
        if max_rounds is not None:
            try:
                max_rounds = int(max_rounds)
                if max_rounds <= 0:
                    return jsonify({
                        "success": False,
                        "error": "max_rounds deve ser um inteiro positivo"
                    }), 400
            except (ValueError, TypeError):
                return jsonify({
                    "success": False,
                    "error": "max_rounds deve ser um inteiro valido"
                }), 400

        if platform not in ['twitter', 'reddit', 'parallel']:
            return jsonify({
                "success": False,
                "error": f"Tipo de plataforma invalido: {platform}, opcoes: twitter/reddit/parallel"
            }), 400

        # Verificar se a simulacao esta pronta
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)

        if not state:
            return jsonify({
                "success": False,
                "error": f"Simulacao não encontrada: {simulation_id}"
            }), 404

        force_restarted = False

        # Tratamento inteligente de status: se o trabalho de preparacao esta concluido, permitir reinicio
        if state.status != SimulationStatus.READY:
            # Verificar se o trabalho de preparacao foi concluido
            is_prepared, prepare_info = _check_simulation_prepared(simulation_id)

            if is_prepared:
                # Trabalho de preparacao concluido, verificar se ha processo em execucao
                if state.status == SimulationStatus.RUNNING:
                    # Verificar se o processo de simulacao esta realmente em execucao
                    run_state = SimulationRunner.get_run_state(simulation_id)
                    if run_state and run_state.runner_status.value == "running":
                        # Processo realmente em execucao
                        if force:
                            # Modo forcado: parar simulacao em execucao
                            logger.info(f"Modo forcado: parando simulacao em execucao {simulation_id}")
                            try:
                                SimulationRunner.stop_simulation(simulation_id)
                            except Exception as e:
                                logger.warning(f"Aviso ao parar simulacao: {str(e)}")
                        else:
                            return jsonify({
                                "success": False,
                                "error": f"Simulacao em execucao, por favor chame a interface /stop primeiro, ou use force=true para forcar reinicio"
                            }), 400

                # Se modo forcado, limpar logs de execucao
                if force:
                    logger.info(f"Modo forcado: limpando logs da simulacao {simulation_id}")
                    cleanup_result = SimulationRunner.cleanup_simulation_logs(simulation_id)
                    if not cleanup_result.get("success"):
                        logger.warning(f"Aviso ao limpar logs: {cleanup_result.get('errors')}")
                    force_restarted = True

                # Processo nao existe ou ja terminou, resetar status para ready
                logger.info(f"Simulacao {simulation_id} trabalho de preparacao concluido, resetando status para ready (status anterior: {state.status.value})")
                state.status = SimulationStatus.READY
                manager._save_simulation_state(state)
            else:
                # Trabalho de preparacao nao concluido
                return jsonify({
                    "success": False,
                    "error": f"Simulacao nao esta pronta, status atual: {state.status.value}, por favor chame a interface /prepare primeiro"
                }), 400

        # Obter graph_id (para atualizacao de memoria do grafo)
        graph_id = None
        if enable_graph_memory_update:
            # Obter graph_id do estado da simulacao ou do projeto
            graph_id = state.graph_id
            if not graph_id:
                # Tentar obter do projeto
                project = ProjectManager.get_project(state.project_id)
                if project:
                    graph_id = project.graph_id

            if not graph_id:
                return jsonify({
                    "success": False,
                    "error": "Ativar atualizacao de memoria do grafo requer um graph_id valido, por favor certifique-se de que o projeto ja construiu o grafo"
                }), 400

            logger.info(f"Atualizacao de memoria do grafo ativada: simulation_id={simulation_id}, graph_id={graph_id}")

        # Iniciar simulacao
        run_state = SimulationRunner.start_simulation(
            simulation_id=simulation_id,
            platform=platform,
            max_rounds=max_rounds,
            enable_graph_memory_update=enable_graph_memory_update,
            graph_id=graph_id
        )

        # Atualizar estado da simulacao
        state.status = SimulationStatus.RUNNING
        manager._save_simulation_state(state)

        response_data = run_state.to_dict()
        if max_rounds:
            response_data['max_rounds_applied'] = max_rounds
        response_data['graph_memory_update_enabled'] = enable_graph_memory_update
        response_data['force_restarted'] = force_restarted
        if enable_graph_memory_update:
            response_data['graph_id'] = graph_id

        return jsonify({
            "success": True,
            "data": response_data
        })

    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400

    except Exception as e:
        logger.error(f"Falha ao iniciar simulacao: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/stop', methods=['POST'])
def stop_simulation():
    """
    Parar simulacao

    Requisicao (JSON):
        {
            "simulation_id": "sim_xxxx"  // Obrigatorio, ID da simulacao
        }

    Retorno:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "runner_status": "stopped",
                "completed_at": "2025-12-01T12:00:00"
            }
        }
    """
    try:
        data = request.get_json() or {}

        simulation_id = data.get('simulation_id')
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "Por favor, forneca o simulation_id"
            }), 400

        run_state = SimulationRunner.stop_simulation(simulation_id)

        # Atualizar estado da simulacao
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        if state:
            state.status = SimulationStatus.PAUSED
            manager._save_simulation_state(state)

        return jsonify({
            "success": True,
            "data": run_state.to_dict()
        })

    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400

    except Exception as e:
        logger.error(f"Falha ao parar simulacao: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Interface de monitoramento de status em tempo real ==============

@simulation_bp.route('/<simulation_id>/run-status', methods=['GET'])
def get_run_status(simulation_id: str):
    """
    Obter status de execucao em tempo real da simulacao (para polling do frontend)

    Retorno:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "runner_status": "running",
                "current_round": 5,
                "total_rounds": 144,
                "progress_percent": 3.5,
                "simulated_hours": 2,
                "total_simulation_hours": 72,
                "twitter_running": true,
                "reddit_running": true,
                "twitter_actions_count": 150,
                "reddit_actions_count": 200,
                "total_actions_count": 350,
                "started_at": "2025-12-01T10:00:00",
                "updated_at": "2025-12-01T10:30:00"
            }
        }
    """
    try:
        run_state = SimulationRunner.get_run_state(simulation_id)

        if not run_state:
            return jsonify({
                "success": True,
                "data": {
                    "simulation_id": simulation_id,
                    "runner_status": "idle",
                    "current_round": 0,
                    "total_rounds": 0,
                    "progress_percent": 0,
                    "twitter_actions_count": 0,
                    "reddit_actions_count": 0,
                    "total_actions_count": 0,
                }
            })

        return jsonify({
            "success": True,
            "data": run_state.to_dict()
        })

    except Exception as e:
        logger.error(f"Falha ao obter status de execucao: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/run-status/detail', methods=['GET'])
def get_run_status_detail(simulation_id: str):
    """
    Obter status detalhado de execucao da simulacao (incluindo todas as acoes)

    Usado para exibir dinamica em tempo real no frontend

    Parâmetros Query:
        platform: Filtrar plataforma (twitter/reddit, opcional)

    Retorno:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "runner_status": "running",
                "current_round": 5,
                ...
                "all_actions": [
                    {
                        "round_num": 5,
                        "timestamp": "2025-12-01T10:30:00",
                        "platform": "twitter",
                        "agent_id": 3,
                        "agent_name": "Agent Name",
                        "action_type": "CREATE_POST",
                        "action_args": {"content": "..."},
                        "result": null,
                        "success": true
                    },
                    ...
                ],
                "twitter_actions": [...],  # Todas as acoes da plataforma Twitter
                "reddit_actions": [...]    # Todas as acoes da plataforma Reddit
            }
        }
    """
    try:
        run_state = SimulationRunner.get_run_state(simulation_id)
        platform_filter = request.args.get('platform')

        if not run_state:
            return jsonify({
                "success": True,
                "data": {
                    "simulation_id": simulation_id,
                    "runner_status": "idle",
                    "all_actions": [],
                    "twitter_actions": [],
                    "reddit_actions": []
                }
            })

        # Obter lista completa de acoes
        all_actions = SimulationRunner.get_all_actions(
            simulation_id=simulation_id,
            platform=platform_filter
        )

        # Obter acoes por plataforma
        twitter_actions = SimulationRunner.get_all_actions(
            simulation_id=simulation_id,
            platform="twitter"
        ) if not platform_filter or platform_filter == "twitter" else []

        reddit_actions = SimulationRunner.get_all_actions(
            simulation_id=simulation_id,
            platform="reddit"
        ) if not platform_filter or platform_filter == "reddit" else []

        # Obter acoes do round atual (recent_actions mostra apenas o round mais recente)
        current_round = run_state.current_round
        recent_actions = SimulationRunner.get_all_actions(
            simulation_id=simulation_id,
            platform=platform_filter,
            round_num=current_round
        ) if current_round > 0 else []

        # Obter informacoes basicas de status
        result = run_state.to_dict()
        result["all_actions"] = [a.to_dict() for a in all_actions]
        result["twitter_actions"] = [a.to_dict() for a in twitter_actions]
        result["reddit_actions"] = [a.to_dict() for a in reddit_actions]
        result["rounds_count"] = len(run_state.rounds)
        # recent_actions mostra apenas o conteudo do round mais recente de ambas as plataformas
        result["recent_actions"] = [a.to_dict() for a in recent_actions]

        return jsonify({
            "success": True,
            "data": result
        })

    except Exception as e:
        logger.error(f"Falha ao obter status detalhado: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/actions', methods=['GET'])
def get_simulation_actions(simulation_id: str):
    """
    Obter historico de acoes dos Agents na simulacao

    Parâmetros Query:
        limit: Quantidade retornada (padrao 100)
        offset: Deslocamento (padrao 0)
        platform: Filtrar plataforma (twitter/reddit)
        agent_id: Filtrar por Agent ID
        round_num: Filtrar por round

    Retorno:
        {
            "success": true,
            "data": {
                "count": 100,
                "actions": [...]
            }
        }
    """
    try:
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        platform = request.args.get('platform')
        agent_id = request.args.get('agent_id', type=int)
        round_num = request.args.get('round_num', type=int)

        actions = SimulationRunner.get_actions(
            simulation_id=simulation_id,
            limit=limit,
            offset=offset,
            platform=platform,
            agent_id=agent_id,
            round_num=round_num
        )

        return jsonify({
            "success": True,
            "data": {
                "count": len(actions),
                "actions": [a.to_dict() for a in actions]
            }
        })

    except Exception as e:
        logger.error(f"Falha ao obter historico de acoes: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/timeline', methods=['GET'])
def get_simulation_timeline(simulation_id: str):
    """
    Obter linha do tempo da simulacao (resumo por round)

    Usado para exibir barra de progresso e visualizacao de linha do tempo no frontend

    Parâmetros Query:
        start_round: Round inicial (padrao 0)
        end_round: Round final (padrao todos)

    Retorna informacoes resumidas de cada round
    """
    try:
        start_round = request.args.get('start_round', 0, type=int)
        end_round = request.args.get('end_round', type=int)

        timeline = SimulationRunner.get_timeline(
            simulation_id=simulation_id,
            start_round=start_round,
            end_round=end_round
        )

        return jsonify({
            "success": True,
            "data": {
                "rounds_count": len(timeline),
                "timeline": timeline
            }
        })

    except Exception as e:
        logger.error(f"Falha ao obter linha do tempo: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/agent-stats', methods=['GET'])
def get_agent_stats(simulation_id: str):
    """
    Obter informacoes estatisticas de cada Agent

    Usado para exibir ranking de atividade dos Agents, distribuicao de acoes etc. no frontend
    """
    try:
        stats = SimulationRunner.get_agent_stats(simulation_id)

        return jsonify({
            "success": True,
            "data": {
                "agents_count": len(stats),
                "stats": stats
            }
        })

    except Exception as e:
        logger.error(f"Falha ao obter estatisticas de Agent: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Interface de consulta ao banco de dados ==============

@simulation_bp.route('/<simulation_id>/posts', methods=['GET'])
def get_simulation_posts(simulation_id: str):
    """
    Obter posts da simulacao

    Parâmetros Query:
        platform: Tipo de plataforma (twitter/reddit)
        limit: Quantidade retornada (padrao 50)
        offset: Deslocamento

    Retorna lista de posts (lidos do banco de dados SQLite)
    """
    try:
        platform = request.args.get('platform', 'reddit')
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)

        sim_dir = os.path.join(
            os.path.dirname(__file__),
            f'../../uploads/simulations/{simulation_id}'
        )

        db_file = f"{platform}_simulation.db"
        db_path = os.path.join(sim_dir, db_file)

        if not os.path.exists(db_path):
            return jsonify({
                "success": True,
                "data": {
                    "platform": platform,
                    "count": 0,
                    "posts": [],
                    "message": "Banco de dados nao encontrado, a simulacao pode nao ter sido executada ainda"
                }
            })

        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT * FROM post
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, (limit, offset))

            posts = [dict(row) for row in cursor.fetchall()]

            cursor.execute("SELECT COUNT(*) FROM post")
            total = cursor.fetchone()[0]

        except sqlite3.OperationalError:
            posts = []
            total = 0

        conn.close()

        return jsonify({
            "success": True,
            "data": {
                "platform": platform,
                "total": total,
                "count": len(posts),
                "posts": posts
            }
        })

    except Exception as e:
        logger.error(f"Falha ao obter posts: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/comments', methods=['GET'])
def get_simulation_comments(simulation_id: str):
    """
    Obter comentarios da simulacao (apenas Reddit)

    Parâmetros Query:
        post_id: Filtrar por ID do post (opcional)
        limit: Quantidade retornada
        offset: Deslocamento
    """
    try:
        post_id = request.args.get('post_id')
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)

        sim_dir = os.path.join(
            os.path.dirname(__file__),
            f'../../uploads/simulations/{simulation_id}'
        )

        db_path = os.path.join(sim_dir, "reddit_simulation.db")

        if not os.path.exists(db_path):
            return jsonify({
                "success": True,
                "data": {
                    "count": 0,
                    "comments": []
                }
            })

        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            if post_id:
                cursor.execute("""
                    SELECT * FROM comment
                    WHERE post_id = ?
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                """, (post_id, limit, offset))
            else:
                cursor.execute("""
                    SELECT * FROM comment
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                """, (limit, offset))

            comments = [dict(row) for row in cursor.fetchall()]

        except sqlite3.OperationalError:
            comments = []

        conn.close()

        return jsonify({
            "success": True,
            "data": {
                "count": len(comments),
                "comments": comments
            }
        })

    except Exception as e:
        logger.error(f"Falha ao obter comentarios: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Interface de entrevista (Interview) ==============

@simulation_bp.route('/interview', methods=['POST'])
def interview_agent():
    """
    Entrevistar um unico Agent

    Nota: Esta funcionalidade requer que o ambiente de simulacao esteja em execucao (apos completar os ciclos de simulacao e entrar no modo de espera de comandos)

    Requisicao (JSON):
        {
            "simulation_id": "sim_xxxx",       // Obrigatorio, ID da simulacao
            "agent_id": 0,                     // Obrigatorio, Agent ID
            "prompt": "Qual e sua opiniao sobre isso?",  // Obrigatorio, pergunta da entrevista
            "platform": "twitter",             // Opcional, especificar plataforma (twitter/reddit)
                                               // Se nao especificado: simulacao dual-platform entrevista ambas as plataformas simultaneamente
            "timeout": 60                      // Opcional, tempo limite (segundos), padrao 60
        }

    Retorno (sem platform especificado, modo dual-platform):
        {
            "success": true,
            "data": {
                "agent_id": 0,
                "prompt": "Qual e sua opiniao sobre isso?",
                "result": {
                    "agent_id": 0,
                    "prompt": "...",
                    "platforms": {
                        "twitter": {"agent_id": 0, "response": "...", "platform": "twitter"},
                        "reddit": {"agent_id": 0, "response": "...", "platform": "reddit"}
                    }
                },
                "timestamp": "2025-12-08T10:00:01"
            }
        }

    Retorno (com platform especificado):
        {
            "success": true,
            "data": {
                "agent_id": 0,
                "prompt": "Qual e sua opiniao sobre isso?",
                "result": {
                    "agent_id": 0,
                    "response": "Eu acho que...",
                    "platform": "twitter",
                    "timestamp": "2025-12-08T10:00:00"
                },
                "timestamp": "2025-12-08T10:00:01"
            }
        }
    """
    try:
        data = request.get_json() or {}

        simulation_id = data.get('simulation_id')
        agent_id = data.get('agent_id')
        prompt = data.get('prompt')
        platform = data.get('platform')  # Opcional: twitter/reddit/None
        timeout = data.get('timeout', 60)

        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "Por favor, forneca o simulation_id"
            }), 400

        if agent_id is None:
            return jsonify({
                "success": False,
                "error": "Por favor, forneca o agent_id"
            }), 400

        if not prompt:
            return jsonify({
                "success": False,
                "error": "Por favor, forneca o prompt (pergunta da entrevista)"
            }), 400

        # Validar parametro platform
        if platform and platform not in ("twitter", "reddit"):
            return jsonify({
                "success": False,
                "error": "O parametro platform so pode ser 'twitter' ou 'reddit'"
            }), 400

        # Verificar estado do ambiente
        if not SimulationRunner.check_env_alive(simulation_id):
            return jsonify({
                "success": False,
                "error": "O ambiente de simulacao nao esta em execucao ou ja foi encerrado. Certifique-se de que a simulacao foi concluida e entrou no modo de espera de comandos."
            }), 400

        # Otimizar prompt, adicionar prefixo para evitar que o Agent chame ferramentas
        optimized_prompt = optimize_interview_prompt(prompt)

        result = SimulationRunner.interview_agent(
            simulation_id=simulation_id,
            agent_id=agent_id,
            prompt=optimized_prompt,
            platform=platform,
            timeout=timeout
        )

        return jsonify({
            "success": result.get("success", False),
            "data": result
        })

    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400

    except TimeoutError as e:
        return jsonify({
            "success": False,
            "error": f"Tempo limite excedido ao aguardar resposta do Interview: {str(e)}"
        }), 504

    except Exception as e:
        logger.error(f"Falha no Interview: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/interview/batch', methods=['POST'])
def interview_agents_batch():
    """
    Entrevistar multiplos Agents em lote

    Nota: Esta funcionalidade requer que o ambiente de simulacao esteja em execucao

    Requisicao (JSON):
        {
            "simulation_id": "sim_xxxx",       // Obrigatorio, ID da simulacao
            "interviews": [                    // Obrigatorio, lista de entrevistas
                {
                    "agent_id": 0,
                    "prompt": "Qual e sua opiniao sobre A?",
                    "platform": "twitter"      // Opcional, especificar plataforma para este Agent
                },
                {
                    "agent_id": 1,
                    "prompt": "Qual e sua opiniao sobre B?"  // Sem platform usa o padrao
                }
            ],
            "platform": "reddit",              // Opcional, plataforma padrao (sobrescrita pelo platform de cada item)
                                               // Se nao especificado: simulacao dual-platform entrevista cada Agent em ambas as plataformas simultaneamente
            "timeout": 120                     // Opcional, tempo limite (segundos), padrao 120
        }

    Retorno:
        {
            "success": true,
            "data": {
                "interviews_count": 2,
                "result": {
                    "interviews_count": 4,
                    "results": {
                        "twitter_0": {"agent_id": 0, "response": "...", "platform": "twitter"},
                        "reddit_0": {"agent_id": 0, "response": "...", "platform": "reddit"},
                        "twitter_1": {"agent_id": 1, "response": "...", "platform": "twitter"},
                        "reddit_1": {"agent_id": 1, "response": "...", "platform": "reddit"}
                    }
                },
                "timestamp": "2025-12-08T10:00:01"
            }
        }
    """
    try:
        data = request.get_json() or {}

        simulation_id = data.get('simulation_id')
        interviews = data.get('interviews')
        platform = data.get('platform')  # Opcional: twitter/reddit/None
        timeout = data.get('timeout', 120)

        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "Por favor, forneca o simulation_id"
            }), 400

        if not interviews or not isinstance(interviews, list):
            return jsonify({
                "success": False,
                "error": "Por favor, forneca interviews (lista de entrevistas)"
            }), 400

        # Validar parametro platform
        if platform and platform not in ("twitter", "reddit"):
            return jsonify({
                "success": False,
                "error": "O parametro platform so pode ser 'twitter' ou 'reddit'"
            }), 400

        # Validar cada item de entrevista
        for i, interview in enumerate(interviews):
            if 'agent_id' not in interview:
                return jsonify({
                    "success": False,
                    "error": f"Item {i+1} da lista de entrevistas esta sem agent_id"
                }), 400
            if 'prompt' not in interview:
                return jsonify({
                    "success": False,
                    "error": f"Item {i+1} da lista de entrevistas esta sem prompt"
                }), 400
            # Validar platform de cada item (se houver)
            item_platform = interview.get('platform')
            if item_platform and item_platform not in ("twitter", "reddit"):
                return jsonify({
                    "success": False,
                    "error": f"O platform do item {i+1} da lista de entrevistas so pode ser 'twitter' ou 'reddit'"
                }), 400

        # Verificar estado do ambiente
        if not SimulationRunner.check_env_alive(simulation_id):
            return jsonify({
                "success": False,
                "error": "O ambiente de simulacao nao esta em execucao ou ja foi encerrado. Certifique-se de que a simulacao foi concluida e entrou no modo de espera de comandos."
            }), 400

        # Otimizar prompt de cada item de entrevista, adicionar prefixo para evitar que o Agent chame ferramentas
        optimized_interviews = []
        for interview in interviews:
            optimized_interview = interview.copy()
            optimized_interview['prompt'] = optimize_interview_prompt(interview.get('prompt', ''))
            optimized_interviews.append(optimized_interview)

        result = SimulationRunner.interview_agents_batch(
            simulation_id=simulation_id,
            interviews=optimized_interviews,
            platform=platform,
            timeout=timeout
        )

        return jsonify({
            "success": result.get("success", False),
            "data": result
        })

    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400

    except TimeoutError as e:
        return jsonify({
            "success": False,
            "error": f"Tempo limite excedido ao aguardar resposta do Interview em lote: {str(e)}"
        }), 504

    except Exception as e:
        logger.error(f"Falha no Interview em lote: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/interview/all', methods=['POST'])
def interview_all_agents():
    """
    Entrevista global - entrevistar todos os Agents com a mesma pergunta

    Nota: Esta funcionalidade requer que o ambiente de simulacao esteja em execucao

    Requisicao (JSON):
        {
            "simulation_id": "sim_xxxx",            // Obrigatorio, ID da simulacao
            "prompt": "Qual e sua opiniao geral sobre isso?",  // Obrigatorio, pergunta da entrevista (mesma para todos os Agents)
            "platform": "reddit",                   // Opcional, especificar plataforma (twitter/reddit)
                                                    // Se nao especificado: simulacao dual-platform entrevista cada Agent em ambas as plataformas simultaneamente
            "timeout": 180                          // Opcional, tempo limite (segundos), padrao 180
        }

    Retorno:
        {
            "success": true,
            "data": {
                "interviews_count": 50,
                "result": {
                    "interviews_count": 100,
                    "results": {
                        "twitter_0": {"agent_id": 0, "response": "...", "platform": "twitter"},
                        "reddit_0": {"agent_id": 0, "response": "...", "platform": "reddit"},
                        ...
                    }
                },
                "timestamp": "2025-12-08T10:00:01"
            }
        }
    """
    try:
        data = request.get_json() or {}

        simulation_id = data.get('simulation_id')
        prompt = data.get('prompt')
        platform = data.get('platform')  # Opcional: twitter/reddit/None
        timeout = data.get('timeout', 180)

        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "Por favor, forneca o simulation_id"
            }), 400

        if not prompt:
            return jsonify({
                "success": False,
                "error": "Por favor, forneca o prompt (pergunta da entrevista)"
            }), 400

        # Validar parametro platform
        if platform and platform not in ("twitter", "reddit"):
            return jsonify({
                "success": False,
                "error": "O parametro platform so pode ser 'twitter' ou 'reddit'"
            }), 400

        # Verificar estado do ambiente
        if not SimulationRunner.check_env_alive(simulation_id):
            return jsonify({
                "success": False,
                "error": "O ambiente de simulacao nao esta em execucao ou ja foi encerrado. Certifique-se de que a simulacao foi concluida e entrou no modo de espera de comandos."
            }), 400

        # Otimizar prompt, adicionar prefixo para evitar que o Agent chame ferramentas
        optimized_prompt = optimize_interview_prompt(prompt)

        result = SimulationRunner.interview_all_agents(
            simulation_id=simulation_id,
            prompt=optimized_prompt,
            platform=platform,
            timeout=timeout
        )

        return jsonify({
            "success": result.get("success", False),
            "data": result
        })

    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400

    except TimeoutError as e:
        return jsonify({
            "success": False,
            "error": f"Tempo limite excedido ao aguardar resposta do Interview global: {str(e)}"
        }), 504

    except Exception as e:
        logger.error(f"Falha no Interview global: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/interview/history', methods=['POST'])
def get_interview_history():
    """
    Obter historico de registros de Interview

    Le todos os registros de Interview do banco de dados da simulacao

    Requisicao (JSON):
        {
            "simulation_id": "sim_xxxx",  // Obrigatorio, ID da simulacao
            "platform": "reddit",          // Opcional, tipo de plataforma (reddit/twitter)
                                           // Se nao especificado, retorna historico de ambas as plataformas
            "agent_id": 0,                 // Opcional, obter apenas historico de entrevistas deste Agent
            "limit": 100                   // Opcional, quantidade retornada, padrao 100
        }

    Retorno:
        {
            "success": true,
            "data": {
                "count": 10,
                "history": [
                    {
                        "agent_id": 0,
                        "response": "Eu acho que...",
                        "prompt": "Qual e sua opiniao sobre isso?",
                        "timestamp": "2025-12-08T10:00:00",
                        "platform": "reddit"
                    },
                    ...
                ]
            }
        }
    """
    try:
        data = request.get_json() or {}

        simulation_id = data.get('simulation_id')
        platform = data.get('platform')  # Se nao especificado, retorna historico de ambas as plataformas
        agent_id = data.get('agent_id')
        limit = data.get('limit', 100)

        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "Por favor, forneca o simulation_id"
            }), 400

        history = SimulationRunner.get_interview_history(
            simulation_id=simulation_id,
            platform=platform,
            agent_id=agent_id,
            limit=limit
        )

        return jsonify({
            "success": True,
            "data": {
                "count": len(history),
                "history": history
            }
        })

    except Exception as e:
        logger.error(f"Falha ao obter historico de Interview: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/env-status', methods=['POST'])
def get_env_status():
    """
    Obter status do ambiente de simulacao

    Verificar se o ambiente de simulacao esta ativo (pode receber comandos de Interview)

    Requisicao (JSON):
        {
            "simulation_id": "sim_xxxx"  // Obrigatorio, ID da simulacao
        }

    Retorno:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "env_alive": true,
                "twitter_available": true,
                "reddit_available": true,
                "message": "Ambiente em execucao, pode receber comandos de Interview"
            }
        }
    """
    try:
        data = request.get_json() or {}

        simulation_id = data.get('simulation_id')

        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "Por favor, forneca o simulation_id"
            }), 400

        env_alive = SimulationRunner.check_env_alive(simulation_id)

        # Obter informacoes de status mais detalhadas
        env_status = SimulationRunner.get_env_status_detail(simulation_id)

        if env_alive:
            message = "Ambiente em execucao, pode receber comandos de Interview"
        else:
            message = "Ambiente nao esta em execucao ou ja foi encerrado"

        return jsonify({
            "success": True,
            "data": {
                "simulation_id": simulation_id,
                "env_alive": env_alive,
                "twitter_available": env_status.get("twitter_available", False),
                "reddit_available": env_status.get("reddit_available", False),
                "message": message
            }
        })

    except Exception as e:
        logger.error(f"Falha ao obter status do ambiente: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/close-env', methods=['POST'])
def close_simulation_env():
    """
    Encerrar ambiente de simulacao

    Envia comando de encerramento para a simulacao, fazendo-a sair graciosamente do modo de espera de comandos.

    Nota: Isso e diferente da interface /stop. /stop forca o encerramento do processo,
    enquanto esta interface permite que a simulacao encerre o ambiente graciosamente e saia.

    Requisicao (JSON):
        {
            "simulation_id": "sim_xxxx",  // Obrigatorio, ID da simulacao
            "timeout": 30                  // Opcional, tempo limite (segundos), padrao 30
        }

    Retorno:
        {
            "success": true,
            "data": {
                "message": "Comando de encerramento do ambiente enviado",
                "result": {...},
                "timestamp": "2025-12-08T10:00:01"
            }
        }
    """
    try:
        data = request.get_json() or {}

        simulation_id = data.get('simulation_id')
        timeout = data.get('timeout', 30)

        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "Por favor, forneca o simulation_id"
            }), 400

        result = SimulationRunner.close_simulation_env(
            simulation_id=simulation_id,
            timeout=timeout
        )

        # Atualizar estado da simulacao
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        if state:
            state.status = SimulationStatus.COMPLETED
            manager._save_simulation_state(state)

        return jsonify({
            "success": result.get("success", False),
            "data": result
        })

    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400

    except Exception as e:
        logger.error(f"Falha ao encerrar ambiente: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500
