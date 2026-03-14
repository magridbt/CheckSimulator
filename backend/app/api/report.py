"""
Rotas da API de Relatorios
Fornece interfaces para geracao, obtencao e conversa de relatorios de simulacao
"""

import os
import traceback
import threading
from flask import request, jsonify, send_file

from . import report_bp
from ..config import Config
from ..services.report_agent import ReportAgent, ReportManager, ReportStatus
from ..services.simulation_manager import SimulationManager
from ..models.project import ProjectManager
from ..models.task import TaskManager, TaskStatus
from ..utils.logger import get_logger

logger = get_logger('checksimulator.api.report')


# ============== Interface de geracao de relatorios ==============

@report_bp.route('/generate', methods=['POST'])
def generate_report():
    """
    Gerar relatorio de analise de simulacao (tarefa assincrona)

    Esta e uma operacao demorada, a interface retorna imediatamente o task_id,
    use GET /api/report/generate/status para consultar o progresso

    Requisicao (JSON):
        {
            "simulation_id": "sim_xxxx",    // Obrigatorio, ID da simulacao
            "force_regenerate": false        // Opcional, forcar regeneracao
        }

    Retorno:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "task_id": "task_xxxx",
                "status": "generating",
                "message": "Tarefa de geracao de relatorio iniciada"
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

        force_regenerate = data.get('force_regenerate', False)

        # Obter informacoes da simulacao
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)

        if not state:
            return jsonify({
                "success": False,
                "error": f"Simulacao não encontrada: {simulation_id}"
            }), 404

        # Verificar se ja existe relatorio
        if not force_regenerate:
            existing_report = ReportManager.get_report_by_simulation(simulation_id)
            if existing_report and existing_report.status == ReportStatus.COMPLETED:
                return jsonify({
                    "success": True,
                    "data": {
                        "simulation_id": simulation_id,
                        "report_id": existing_report.report_id,
                        "status": "completed",
                        "message": "Relatorio ja existe",
                        "already_generated": True
                    }
                })

        # Obter informacoes do projeto
        project = ProjectManager.get_project(state.project_id)
        if not project:
            return jsonify({
                "success": False,
                "error": f"Projeto não encontrado: {state.project_id}"
            }), 404

        graph_id = state.graph_id or project.graph_id
        if not graph_id:
            return jsonify({
                "success": False,
                "error": "ID do grafo ausente, certifique-se de que o grafo foi construido"
            }), 400

        simulation_requirement = project.simulation_requirement
        if not simulation_requirement:
            return jsonify({
                "success": False,
                "error": "Descricao do requisito de simulacao ausente"
            }), 400

        # Gerar report_id antecipadamente para retornar imediatamente ao frontend
        import uuid
        report_id = f"report_{uuid.uuid4().hex[:12]}"

        # Criar tarefa assincrona
        task_manager = TaskManager()
        task_id = task_manager.create_task(
            task_type="report_generate",
            metadata={
                "simulation_id": simulation_id,
                "graph_id": graph_id,
                "report_id": report_id
            }
        )

        # Definir tarefa em segundo plano
        def run_generate():
            try:
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.PROCESSING,
                    progress=0,
                    message="Inicializando Report Agent..."
                )

                # Criar Report Agent
                agent = ReportAgent(
                    graph_id=graph_id,
                    simulation_id=simulation_id,
                    simulation_requirement=simulation_requirement
                )

                # Callback de progresso
                def progress_callback(stage, progress, message):
                    task_manager.update_task(
                        task_id,
                        progress=progress,
                        message=f"[{stage}] {message}"
                    )

                # Gerar relatorio (passando report_id gerado previamente)
                report = agent.generate_report(
                    progress_callback=progress_callback,
                    report_id=report_id
                )

                # Salvar relatorio
                ReportManager.save_report(report)

                if report.status == ReportStatus.COMPLETED:
                    task_manager.complete_task(
                        task_id,
                        result={
                            "report_id": report.report_id,
                            "simulation_id": simulation_id,
                            "status": "completed"
                        }
                    )
                else:
                    task_manager.fail_task(task_id, report.error or "Falha ao gerar relatorio")

            except Exception as e:
                logger.error(f"Falha ao gerar relatorio: {str(e)}")
                task_manager.fail_task(task_id, str(e))

        # Iniciar thread em segundo plano
        thread = threading.Thread(target=run_generate, daemon=True)
        thread.start()

        return jsonify({
            "success": True,
            "data": {
                "simulation_id": simulation_id,
                "report_id": report_id,
                "task_id": task_id,
                "status": "generating",
                "message": "Tarefa de geracao de relatorio iniciada, consulte o progresso via /api/report/generate/status",
                "already_generated": False
            }
        })

    except Exception as e:
        logger.error(f"Falha ao iniciar tarefa de geracao de relatorio: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/generate/status', methods=['POST'])
def get_generate_status():
    """
    Consultar progresso da tarefa de geracao de relatorio

    Requisicao (JSON):
        {
            "task_id": "task_xxxx",         // Opcional, task_id retornado pelo generate
            "simulation_id": "sim_xxxx"     // Opcional, ID da simulacao
        }

    Retorno:
        {
            "success": true,
            "data": {
                "task_id": "task_xxxx",
                "status": "processing|completed|failed",
                "progress": 45,
                "message": "..."
            }
        }
    """
    try:
        data = request.get_json() or {}

        task_id = data.get('task_id')
        simulation_id = data.get('simulation_id')

        # Se simulation_id fornecido, verificar primeiro se ja existe relatorio concluido
        if simulation_id:
            existing_report = ReportManager.get_report_by_simulation(simulation_id)
            if existing_report and existing_report.status == ReportStatus.COMPLETED:
                return jsonify({
                    "success": True,
                    "data": {
                        "simulation_id": simulation_id,
                        "report_id": existing_report.report_id,
                        "status": "completed",
                        "progress": 100,
                        "message": "Relatorio ja foi gerado",
                        "already_completed": True
                    }
                })

        if not task_id:
            return jsonify({
                "success": False,
                "error": "Por favor, forneca task_id ou simulation_id"
            }), 400

        task_manager = TaskManager()
        task = task_manager.get_task(task_id)

        if not task:
            return jsonify({
                "success": False,
                "error": f"Tarefa não encontrada: {task_id}"
            }), 404

        return jsonify({
            "success": True,
            "data": task.to_dict()
        })

    except Exception as e:
        logger.error(f"Falha ao consultar estado da tarefa: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============== Interface de obtencao de relatorios ==============

@report_bp.route('/<report_id>', methods=['GET'])
def get_report(report_id: str):
    """
    Obter detalhes do relatorio

    Retorno:
        {
            "success": true,
            "data": {
                "report_id": "report_xxxx",
                "simulation_id": "sim_xxxx",
                "status": "completed",
                "outline": {...},
                "markdown_content": "...",
                "created_at": "...",
                "completed_at": "..."
            }
        }
    """
    try:
        report = ReportManager.get_report(report_id)

        if not report:
            return jsonify({
                "success": False,
                "error": f"Relatorio não encontrado: {report_id}"
            }), 404

        return jsonify({
            "success": True,
            "data": report.to_dict()
        })

    except Exception as e:
        logger.error(f"Falha ao obter relatorio: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/by-simulation/<simulation_id>', methods=['GET'])
def get_report_by_simulation(simulation_id: str):
    """
    Obter relatorio por ID da simulacao

    Retorno:
        {
            "success": true,
            "data": {
                "report_id": "report_xxxx",
                ...
            }
        }
    """
    try:
        report = ReportManager.get_report_by_simulation(simulation_id)

        if not report:
            return jsonify({
                "success": False,
                "error": f"Esta simulacao ainda nao tem relatorio: {simulation_id}",
                "has_report": False
            }), 404

        return jsonify({
            "success": True,
            "data": report.to_dict(),
            "has_report": True
        })

    except Exception as e:
        logger.error(f"Falha ao obter relatorio: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/list', methods=['GET'])
def list_reports():
    """
    Listar todos os relatorios

    Parâmetros Query:
        simulation_id: Filtrar por ID da simulacao (opcional)
        limit: Limite de quantidade retornada (padrao 50)

    Retorno:
        {
            "success": true,
            "data": [...],
            "count": 10
        }
    """
    try:
        simulation_id = request.args.get('simulation_id')
        limit = request.args.get('limit', 50, type=int)

        reports = ReportManager.list_reports(
            simulation_id=simulation_id,
            limit=limit
        )

        return jsonify({
            "success": True,
            "data": [r.to_dict() for r in reports],
            "count": len(reports)
        })

    except Exception as e:
        logger.error(f"Falha ao listar relatorios: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/<report_id>/download', methods=['GET'])
def download_report(report_id: str):
    """
    Baixar relatorio (formato Markdown)

    Retorna arquivo Markdown
    """
    try:
        report = ReportManager.get_report(report_id)

        if not report:
            return jsonify({
                "success": False,
                "error": f"Relatorio não encontrado: {report_id}"
            }), 404

        md_path = ReportManager._get_report_markdown_path(report_id)

        if not os.path.exists(md_path):
            # Se o arquivo MD nao existe, gerar um arquivo temporario
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
                f.write(report.markdown_content)
                temp_path = f.name

            return send_file(
                temp_path,
                as_attachment=True,
                download_name=f"{report_id}.md"
            )

        return send_file(
            md_path,
            as_attachment=True,
            download_name=f"{report_id}.md"
        )

    except Exception as e:
        logger.error(f"Falha ao baixar relatorio: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/<report_id>', methods=['DELETE'])
def delete_report(report_id: str):
    """Excluir relatorio"""
    try:
        success = ReportManager.delete_report(report_id)

        if not success:
            return jsonify({
                "success": False,
                "error": f"Relatorio não encontrado: {report_id}"
            }), 404

        return jsonify({
            "success": True,
            "message": f"Relatorio excluido: {report_id}"
        })

    except Exception as e:
        logger.error(f"Falha ao excluir relatorio: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Interface de conversa com Report Agent ==============

@report_bp.route('/chat', methods=['POST'])
def chat_with_report_agent():
    """
    Conversar com Report Agent

    Report Agent pode chamar ferramentas de busca autonomamente durante a conversa para responder perguntas

    Requisicao (JSON):
        {
            "simulation_id": "sim_xxxx",        // Obrigatorio, ID da simulacao
            "message": "Por favor, explique a tendencia da opiniao publica",    // Obrigatorio, mensagem do usuario
            "chat_history": [                   // Opcional, historico de conversa
                {"role": "user", "content": "..."},
                {"role": "assistant", "content": "..."}
            ]
        }

    Retorno:
        {
            "success": true,
            "data": {
                "response": "Resposta do Agent...",
                "tool_calls": [lista de ferramentas chamadas],
                "sources": [fontes de informacao]
            }
        }
    """
    try:
        data = request.get_json() or {}

        simulation_id = data.get('simulation_id')
        message = data.get('message')
        chat_history = data.get('chat_history', [])

        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "Por favor, forneca o simulation_id"
            }), 400

        if not message:
            return jsonify({
                "success": False,
                "error": "Por favor, forneca a message"
            }), 400

        # Obter informacoes da simulacao e do projeto
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)

        if not state:
            return jsonify({
                "success": False,
                "error": f"Simulacao não encontrada: {simulation_id}"
            }), 404

        project = ProjectManager.get_project(state.project_id)
        if not project:
            return jsonify({
                "success": False,
                "error": f"Projeto não encontrado: {state.project_id}"
            }), 404

        graph_id = state.graph_id or project.graph_id
        if not graph_id:
            return jsonify({
                "success": False,
                "error": "ID do grafo ausente"
            }), 400

        simulation_requirement = project.simulation_requirement or ""

        # Criar Agent e conduzir conversa
        agent = ReportAgent(
            graph_id=graph_id,
            simulation_id=simulation_id,
            simulation_requirement=simulation_requirement
        )

        result = agent.chat(message=message, chat_history=chat_history)

        return jsonify({
            "success": True,
            "data": result
        })

    except Exception as e:
        logger.error(f"Falha na conversa: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Interface de progresso e secoes do relatorio ==============

@report_bp.route('/<report_id>/progress', methods=['GET'])
def get_report_progress(report_id: str):
    """
    Obter progresso de geracao do relatorio (em tempo real)

    Retorno:
        {
            "success": true,
            "data": {
                "status": "generating",
                "progress": 45,
                "message": "Gerando secao: Descobertas principais",
                "current_section": "Descobertas principais",
                "completed_sections": ["Resumo executivo", "Contexto da simulacao"],
                "updated_at": "2025-12-09T..."
            }
        }
    """
    try:
        progress = ReportManager.get_progress(report_id)

        if not progress:
            return jsonify({
                "success": False,
                "error": f"Relatorio nao encontrado ou informacoes de progresso indisponiveis: {report_id}"
            }), 404

        return jsonify({
            "success": True,
            "data": progress
        })

    except Exception as e:
        logger.error(f"Falha ao obter progresso do relatorio: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/<report_id>/sections', methods=['GET'])
def get_report_sections(report_id: str):
    """
    Obter lista de secoes geradas (saida por secao)

    O frontend pode fazer polling desta interface para obter conteudo de secoes ja geradas, sem precisar aguardar o relatorio completo

    Retorno:
        {
            "success": true,
            "data": {
                "report_id": "report_xxxx",
                "sections": [
                    {
                        "filename": "section_01.md",
                        "section_index": 1,
                        "content": "## Resumo executivo\\n\\n..."
                    },
                    ...
                ],
                "total_sections": 3,
                "is_complete": false
            }
        }
    """
    try:
        sections = ReportManager.get_generated_sections(report_id)

        # Obter status do relatorio
        report = ReportManager.get_report(report_id)
        is_complete = report is not None and report.status == ReportStatus.COMPLETED

        return jsonify({
            "success": True,
            "data": {
                "report_id": report_id,
                "sections": sections,
                "total_sections": len(sections),
                "is_complete": is_complete
            }
        })

    except Exception as e:
        logger.error(f"Falha ao obter lista de secoes: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/<report_id>/section/<int:section_index>', methods=['GET'])
def get_single_section(report_id: str, section_index: int):
    """
    Obter conteudo de uma unica secao

    Retorno:
        {
            "success": true,
            "data": {
                "filename": "section_01.md",
                "content": "## Resumo executivo\\n\\n..."
            }
        }
    """
    try:
        section_path = ReportManager._get_section_path(report_id, section_index)

        if not os.path.exists(section_path):
            return jsonify({
                "success": False,
                "error": f"Secao nao encontrada: section_{section_index:02d}.md"
            }), 404

        with open(section_path, 'r', encoding='utf-8') as f:
            content = f.read()

        return jsonify({
            "success": True,
            "data": {
                "filename": f"section_{section_index:02d}.md",
                "section_index": section_index,
                "content": content
            }
        })

    except Exception as e:
        logger.error(f"Falha ao obter conteudo da secao: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500
