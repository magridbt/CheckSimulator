"""
CheckSimulator Backend - Fábrica de aplicação Flask
"""

import os
import warnings

# Suprimir avisos de resource_tracker do multiprocessing (vindos de bibliotecas de terceiros como transformers)
# Precisa ser definido antes de todas as outras importações
warnings.filterwarnings("ignore", message=".*resource_tracker.*")

from flask import Flask, request
from flask_cors import CORS

from .config import Config
from .utils.logger import setup_logger, get_logger


def create_app(config_class=Config):
    """Função fábrica da aplicação Flask"""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Configurar codificação JSON: garantir exibição direta de caracteres especiais (em vez do formato \uXXXX)
    # Flask >= 2.3 usa app.json.ensure_ascii, versões anteriores usam a configuração JSON_AS_ASCII
    if hasattr(app, 'json') and hasattr(app.json, 'ensure_ascii'):
        app.json.ensure_ascii = False

    # Configurar logs
    logger = setup_logger('checksimulator')

    # Imprimir informações de inicialização apenas no subprocesso do reloader (evitar impressão dupla no modo debug)
    is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    debug_mode = app.config.get('DEBUG', False)
    should_log_startup = not debug_mode or is_reloader_process

    if should_log_startup:
        logger.info("=" * 50)
        logger.info("CheckSimulator Backend iniciando...")
        logger.info("=" * 50)

    # Habilitar CORS
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # Registrar função de limpeza de processos de simulação (garantir que todos os processos sejam encerrados ao desligar o servidor)
    from .services.simulation_runner import SimulationRunner
    SimulationRunner.register_cleanup()
    if should_log_startup:
        logger.info("Função de limpeza de processos de simulação registrada")

    # Middleware de log de requisições
    @app.before_request
    def log_request():
        logger = get_logger('checksimulator.request')
        logger.debug(f"Requisição: {request.method} {request.path}")
        if request.content_type and 'json' in request.content_type:
            logger.debug(f"Corpo da requisição: {request.get_json(silent=True)}")

    @app.after_request
    def log_response(response):
        logger = get_logger('checksimulator.request')
        logger.debug(f"Resposta: {response.status_code}")
        return response

    # Registrar blueprints
    from .api import graph_bp, simulation_bp, report_bp
    app.register_blueprint(graph_bp, url_prefix='/api/graph')
    app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
    app.register_blueprint(report_bp, url_prefix='/api/report')

    # Health check
    @app.route('/health')
    def health():
        return {'status': 'ok', 'service': 'CheckSimulator Backend'}

    if should_log_startup:
        logger.info("CheckSimulator Backend inicialização concluída")

    return app
