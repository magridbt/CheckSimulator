#!/usr/bin/env python3
"""Medidor de gasto do CheckSimulator.

Fica entre o CheckSimulator e a OpenAI (127.0.0.1:5099). Para cada chamada:
- confere se o gasto já chegou ao teto aprovado; se chegou, BLOQUEIA (não envia);
- envia para a OpenAI, lê os tokens usados e grava em registros/gastos.jsonl.

Teto e preços ficam em registros/teto.json (editado por cs.py teto ...).
"""
import http.client
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

RAIZ = Path(__file__).resolve().parent.parent
REG = RAIZ / "registros"
REG.mkdir(exist_ok=True)
GASTOS = REG / "gastos.jsonl"
TETO = REG / "teto.json"
PORTA = int(os.environ.get("MEDIDOR_PORTA", "5099"))

# Preço padrão em US$ por 1 milhão de tokens (conferir na OpenAI antes de cada orçamento)
# Fonte: developers.openai.com/api/docs/pricing (Standard, contexto curto), conferido em 10/11/2026
PRECOS_PADRAO = {
    "gpt-4o-mini": {"entrada": 0.15, "entrada_cache": 0.075, "saida": 0.60},
    "gpt-5-nano": {"entrada": 0.05, "entrada_cache": 0.005, "saida": 0.40},
    "gpt-5-mini": {"entrada": 0.25, "entrada_cache": 0.025, "saida": 2.00},
    "gpt-6-luna": {"entrada": 0.10, "entrada_cache": 0.01, "saida": 0.50},
    "gpt-6.1-terra": {"entrada": 1.00, "entrada_cache": 0.05, "saida": 5.00},
    "gpt-6.1-sol": {"entrada": 2.00, "entrada_cache": 0.10, "saida": 10.00},
    "gpt-6-sol": {"entrada": 2.00, "entrada_cache": 0.20, "saida": 10.00},
    "gpt-6-astra": {"entrada": 10.00, "entrada_cache": 1.00, "saida": 50.00},
}

# Modelos de raciocínio (GPT-5/6, o-series) recusam temperature e max_tokens
RACIOCINIO = ("gpt-5", "gpt-6", "o1", "o3", "o4")

_lock = threading.Lock()


def ler_env():
    env = {}
    for linha in (RAIZ / ".env").read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            k, v = linha.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def config():
    if TETO.exists():
        return json.loads(TETO.read_text(encoding="utf-8"))
    return {"teto_usd": 0.0, "precos": PRECOS_PADRAO}


def total_gasto(desde=None):
    total = 0.0
    if GASTOS.exists():
        for linha in GASTOS.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(linha)
            except ValueError:
                continue
            if desde is None or r["ts"] >= desde:
                total += r["usd"]
    return total


def custo(modelo, uso, precos):
    p, maior = None, 0
    for nome, valores in precos.items():
        if modelo and modelo.startswith(nome) and len(nome) > maior:
            p, maior = valores, len(nome)
    if p is None:
        return None
    entrada = uso.get("prompt_tokens", 0) or 0
    cache = (uso.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0
    saida = uso.get("completion_tokens", 0) or 0
    return ((entrada - cache) * p["entrada"] + cache * p.get("entrada_cache", p["entrada"]) + saida * p["saida"]) / 1e6


class Medidor(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _erro(self, codigo, msg):
        corpo = json.dumps({"error": {"message": msg, "type": "checksimulator_teto"}}).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        if self.path == "/medidor/status":
            cfg = config()
            corpo = json.dumps({"gasto_usd": round(total_gasto(cfg.get("desde")), 6),
                                "teto_usd": cfg.get("teto_usd", 0)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)
            return
        self._repassar(b"")

    def do_POST(self):
        tam = int(self.headers.get("Content-Length", 0) or 0)
        self._repassar(self.rfile.read(tam) if tam else b"")

    def _repassar(self, corpo):
        cfg = config()
        gasto = total_gasto(cfg.get("desde"))
        teto = float(cfg.get("teto_usd", 0))
        if gasto >= teto:
            self._erro(429, f"CheckSimulator: teto aprovado atingido (gasto US$ {gasto:.4f} de US$ {teto:.2f}). Nada foi enviado.")
            return
        modelo, stream = None, False
        if corpo:
            try:
                req = json.loads(corpo)
                modelo, stream = req.get("model"), bool(req.get("stream"))
                if modelo and modelo.startswith(RACIOCINIO):
                    if req.get("temperature") not in (None, 1):
                        req.pop("temperature")
                    req.pop("top_p", None)
                    if "max_tokens" in req:
                        req["max_completion_tokens"] = req.pop("max_tokens")
                    if req.get("tools") and "/chat/completions" in self.path:
                        req["reasoning_effort"] = "none"  # exigido pela OpenAI para tools no chat/completions
                    corpo = json.dumps(req).encode()
                if stream:
                    req.setdefault("stream_options", {})["include_usage"] = True
                    corpo = json.dumps(req).encode()
            except ValueError:
                pass
        if modelo and custo(modelo, {}, cfg.get("precos", PRECOS_PADRAO)) is None:
            self._erro(400, f"CheckSimulator: modelo '{modelo}' sem preço cadastrado no medidor. Bloqueado.")
            return

        env = ler_env()
        alvo = urlsplit(env.get("MEDIDOR_UPSTREAM", "https://api.openai.com/v1"))
        caminho = self.path
        base = alvo.path.rstrip("/")
        if base and not caminho.startswith(base):
            caminho = base + caminho
        cab = {k: v for k, v in self.headers.items()
               if k.lower() not in ("host", "content-length", "accept-encoding", "connection")}
        cab["Host"] = alvo.netloc
        cab["Content-Length"] = str(len(corpo))
        cab["Accept-Encoding"] = "identity"
        conn = http.client.HTTPSConnection(alvo.netloc, timeout=600)
        try:
            conn.request(self.command, caminho, body=corpo or None, headers=cab)
            resp = conn.getresponse()
            self.send_response(resp.status)
            for k, v in resp.getheaders():
                if k.lower() not in ("transfer-encoding", "connection", "content-length", "content-encoding"):
                    self.send_header(k, v)
            uso = None
            if stream and "text/event-stream" in (resp.getheader("Content-Type") or ""):
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                buffer = b""
                while True:
                    bloco = resp.read1(65536) if hasattr(resp, "read1") else resp.read(65536)
                    if not bloco:
                        break
                    buffer += bloco
                    self.wfile.write(f"{len(bloco):X}\r\n".encode() + bloco + b"\r\n")
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
                for linha in buffer.decode("utf-8", "ignore").splitlines():
                    if linha.startswith("data: {") and '"usage"' in linha:
                        try:
                            u = json.loads(linha[6:]).get("usage")
                            if u:
                                uso = u
                        except ValueError:
                            pass
            else:
                dados = resp.read()
                self.send_header("Content-Length", str(len(dados)))
                self.end_headers()
                self.wfile.write(dados)
                try:
                    j = json.loads(dados)
                    uso = j.get("usage")
                    modelo = j.get("model", modelo)
                except ValueError:
                    pass
            if uso:
                usd = custo(modelo, uso, cfg.get("precos", PRECOS_PADRAO)) or 0.0
                with _lock, GASTOS.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"ts": time.time(), "modelo": modelo, "rota": self.path,
                                        "entrada": uso.get("prompt_tokens", 0),
                                        "saida": uso.get("completion_tokens", 0),
                                        "usd": usd}) + "\n")
        except Exception as e:  # noqa: BLE001
            try:
                self._erro(502, f"CheckSimulator medidor: falha ao falar com a OpenAI: {e}")
            except Exception:  # noqa: BLE001
                pass
        finally:
            conn.close()


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORTA), Medidor)
    print(f"Medidor ativo em http://127.0.0.1:{PORTA}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)
