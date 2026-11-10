#!/usr/bin/env python3
"""cs.py — usa o CheckSimulator pelo terminal/chat, sem a tela.

Etapas (cada uma que gasta créditos passa pelo medidor com teto):
  ligar | desligar | status
  teto <usd>                      define o teto aprovado (zera a contagem a partir de agora)
  gasto                           mostra gasto x teto e detalhe por etapa
  novo --nome N --pergunta P ARQ...   envia material, gera ontologia e constrói o grafo   [GASTA]
  reconstruir --projeto ID        refaz o grafo de um projeto que falhou                   [GASTA]
  preparar --projeto ID [--plataforma reddit|twitter|ambas]   cria agentes + configuração   [GASTA]
  perfis --sim ID                 lista os agentes criados
  rodar --sim ID --rodadas N [--plataforma reddit|twitter|parallel]                        [GASTA]
  posts --sim ID [--limite 50]    o que os agentes publicaram
  relatorio --sim ID [--saida arquivo.md]                                                  [GASTA]
  entrevistar --sim ID --agente N --pergunta P [--plataforma reddit]                       [GASTA]
  entrevistar-todos --sim ID --pergunta P [--plataforma reddit]                            [GASTA]
  chat --sim ID --msg P           pergunta ao ReportAgent                                  [GASTA]
  fechar --sim ID                 encerra o ambiente da simulação
"""
import argparse
import json
import mimetypes
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
REG = RAIZ / "registros"
REG.mkdir(exist_ok=True)
API = "http://127.0.0.1:5001"
MEDIDOR = "http://127.0.0.1:5099"
IDIOMA = {"Accept-Language": "pt"}


def chamar(metodo, rota, dados=None, timeout=600, base=API):
    cab = {"Content-Type": "application/json", **IDIOMA}
    corpo = json.dumps(dados).encode() if dados is not None else None
    req = urllib.request.Request(base + rota, data=corpo, headers=cab, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            j = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            j = json.loads(e.read())
        except ValueError:
            j = {"success": False, "error": f"HTTP {e.code}"}
    if j.get("success") is False:
        sys.exit(f"ERRO: {j.get('error') or j.get('message')}")
    return j.get("data", j)


def enviar_arquivos(rota, campos, arquivos):
    fronteira = uuid.uuid4().hex
    partes = []
    for k, v in campos.items():
        partes.append(f'--{fronteira}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for arq in arquivos:
        p = Path(arq)
        tipo = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        partes.append(f'--{fronteira}\r\nContent-Disposition: form-data; name="files"; filename="{p.name}"\r\n'
                      f'Content-Type: {tipo}\r\n\r\n'.encode() + p.read_bytes() + b"\r\n")
    partes.append(f"--{fronteira}--\r\n".encode())
    req = urllib.request.Request(API + rota, data=b"".join(partes), method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={fronteira}", **IDIOMA})
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            j = json.loads(r.read())
    except urllib.error.HTTPError as e:
        j = json.loads(e.read() or b'{"success":false,"error":"HTTP"}')
    if not j.get("success"):
        sys.exit(f"ERRO: {j.get('error')}")
    return j["data"]


def gasto_txt():
    try:
        s = chamar("GET", "/medidor/status", base=MEDIDOR, timeout=5)
        return f"gasto US$ {s['gasto_usd']:.4f} de teto US$ {s['teto_usd']:.2f}"
    except Exception:  # noqa: BLE001
        return "medidor DESLIGADO"


def esperar(funcao, fim, intervalo=10, rotulo=""):
    ultimo = None
    while True:
        d = funcao()
        msg = f"{rotulo} {d.get('status') or d.get('runner_status')} {d.get('progress', d.get('progress_percent', ''))}% {d.get('message', '')[:90]} | {gasto_txt()}"
        if msg != ultimo:
            print(msg, flush=True)
            ultimo = msg
        estado = d.get("status") or d.get("runner_status")
        if estado in fim:
            return d
        if estado == "failed":
            sys.exit(f"FALHOU: {d.get('error') or d.get('message')}")
        time.sleep(intervalo)


def ativo(url):
    try:
        urllib.request.urlopen(url, timeout=3)
        return True
    except Exception:  # noqa: BLE001
        return False


def cmd_ligar(a):
    env = (RAIZ / ".env").read_text(encoding="utf-8")
    if "127.0.0.1:5099" not in env:
        sys.exit("ERRO: .env não aponta LLM_BASE_URL para o medidor (http://127.0.0.1:5099/v1). Nada ligado.")
    if not ativo(MEDIDOR + "/medidor/status"):
        subprocess.Popen([sys.executable, "-I", str(RAIZ / "ferramentas" / "medidor.py")],
                         stdout=open(REG / "medidor.log", "a"), stderr=subprocess.STDOUT, start_new_session=True)
    if not ativo(API + "/health"):
        subprocess.Popen(["uv", "run", "python", "run.py"], cwd=RAIZ / "backend",
                         stdout=open(REG / "backend.log", "a"), stderr=subprocess.STDOUT, start_new_session=True)
    for _ in range(60):
        if ativo(API + "/health") and ativo(MEDIDOR + "/medidor/status"):
            print("CheckSimulator ligado (API 5001 + medidor 5099).", gasto_txt())
            return
        time.sleep(1)
    sys.exit("ERRO: não ligou em 60 s; ver registros/backend.log e registros/medidor.log")


def cmd_desligar(a):
    for porta in (5001, 5099):
        pids = subprocess.run(["lsof", "-t", f"-iTCP:{porta}", "-sTCP:LISTEN"], capture_output=True, text=True).stdout.split()
        for pid in pids:
            subprocess.run(["kill", pid])
    print("Desligado.")


def cmd_status(a):
    print("API:", "ligada" if ativo(API + "/health") else "desligada", "|", gasto_txt())


def cmd_teto(a):
    arq = REG / "teto.json"
    cfg = json.loads(arq.read_text()) if arq.exists() else {}
    from importlib.util import spec_from_file_location, module_from_spec
    spec = spec_from_file_location("medidor", RAIZ / "ferramentas" / "medidor.py")
    m = module_from_spec(spec)
    spec.loader.exec_module(m)
    cfg.setdefault("precos", m.PRECOS_PADRAO)
    cfg["teto_usd"] = float(a.usd)
    cfg["desde"] = time.time()
    cfg["definido_em"] = time.strftime("%Y-%m-%d %H:%M")
    cfg["motivo"] = a.motivo or ""
    arq.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
    print(f"Teto definido: US$ {cfg['teto_usd']:.2f} (contagem zerada agora).")


def cmd_gasto(a):
    cfg = json.loads((REG / "teto.json").read_text()) if (REG / "teto.json").exists() else {}
    desde = cfg.get("desde", 0)
    por_rota, total, n = {}, 0.0, 0
    arq = REG / "gastos.jsonl"
    if arq.exists():
        for linha in arq.read_text().splitlines():
            r = json.loads(linha)
            if r["ts"] >= desde:
                por_rota.setdefault(r["modelo"], [0, 0, 0, 0.0])
                x = por_rota[r["modelo"]]
                x[0] += 1; x[1] += r["entrada"]; x[2] += r["saida"]; x[3] += r["usd"]
                total += r["usd"]; n += 1
    print(f"Teto: US$ {cfg.get('teto_usd', 0):.2f} (desde {cfg.get('definido_em', '-')}) | gasto: US$ {total:.4f} em {n} chamadas")
    for mod, (c, e, s, u) in por_rota.items():
        print(f"  {mod}: {c} chamadas, {e} tokens entrada, {s} saída, US$ {u:.4f}")


def cmd_novo(a):
    d = enviar_arquivos("/api/graph/ontology/generate",
                        {"project_name": a.nome, "simulation_requirement": a.pergunta,
                         "additional_context": a.contexto or ""}, a.arquivos)
    pid = d["project_id"]
    ont = d.get("ontology", {})
    print(f"Projeto {pid}: {len(ont.get('entity_types', []))} tipos de entidade, {len(ont.get('edge_types', []))} tipos de relação")
    print("Entidades:", ", ".join(e.get("name", "") for e in ont.get("entity_types", [])))
    construir(pid)


def cmd_reconstruir(a):
    construir(a.projeto, force=True)


def construir(pid, force=False):
    t = chamar("POST", "/api/graph/build", {"project_id": pid, "force": force})
    esperar(lambda: chamar("GET", f"/api/graph/task/{t['task_id']}"), {"completed"}, rotulo="grafo")
    proj = chamar("GET", f"/api/graph/project/{pid}")
    print(json.dumps({"project_id": pid, "graph_id": proj.get("graph_id")}, ensure_ascii=False))


def cmd_preparar(a):
    tw = a.plataforma in ("twitter", "ambas")
    rd = a.plataforma in ("reddit", "ambas")
    s = chamar("POST", "/api/simulation/create", {"project_id": a.projeto, "enable_twitter": tw, "enable_reddit": rd})
    sid = s["simulation_id"]
    print("Simulação:", sid)
    p = chamar("POST", "/api/simulation/prepare", {"simulation_id": sid})
    if not p.get("already_prepared"):
        esperar(lambda: chamar("POST", "/api/simulation/prepare/status", {"simulation_id": sid, "task_id": p.get("task_id")}),
                {"completed", "ready"}, rotulo="preparo")
    st = chamar("GET", f"/api/simulation/{sid}")
    cfg = chamar("GET", f"/api/simulation/{sid}/config")
    tempo = cfg.get("time_config", {}) if isinstance(cfg, dict) else {}
    print(json.dumps({"simulation_id": sid, "agentes": st.get("profiles_count"), "entidades": st.get("entities_count"),
                      "horas_simuladas": tempo.get("total_simulation_hours"), "minutos_por_rodada": tempo.get("minutes_per_round"),
                      "agentes_por_hora": [tempo.get("agents_per_hour_min"), tempo.get("agents_per_hour_max")],
                      "gasto": gasto_txt()}, ensure_ascii=False, indent=1))


def cmd_perfis(a):
    d = chamar("GET", f"/api/simulation/{a.sim}/profiles" + (f"?platform={a.plataforma}" if a.plataforma else ""))
    perfis = d.get("profiles", d) if isinstance(d, dict) else d
    for i, p in enumerate(perfis):
        print(f"[{p.get('user_id', i)}] {p.get('name') or p.get('username')} | {p.get('age', '')} {p.get('gender', '')} {p.get('profession', '')} | {(p.get('bio') or '')[:120]}")


def cmd_rodar(a):
    # Horário simulado de início (0–23). Começar à meia-noite deixa rodadas curtas sem ninguém ativo.
    arq = RAIZ / "backend" / "uploads" / "simulations" / a.sim / "simulation_config.json"
    cfg = json.loads(arq.read_text(encoding="utf-8"))
    cfg.setdefault("time_config", {})["start_hour"] = a.inicio
    arq.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Início simulado às {a.inicio}h, {a.rodadas} rodadas.")
    chamar("POST", "/api/simulation/start", {"simulation_id": a.sim, "platform": a.plataforma,
                                             "max_rounds": a.rodadas, "force": a.refazer})
    inicio, ultimo = time.time(), None
    while True:
        d = chamar("GET", f"/api/simulation/{a.sim}/run-status")
        linha = f"rodada {d.get('current_round')}/{d.get('total_rounds')} {d.get('runner_status')} | {gasto_txt()}"
        if linha != ultimo:
            print(linha, flush=True); ultimo = linha
        if d.get("runner_status") == "failed":
            sys.exit(f"FALHOU: {d.get('error')}")
        terminou = d.get("runner_status") in ("completed", "stopped") or d.get("reddit_completed") or d.get("twitter_completed")
        if terminou or (d.get("total_rounds") and (d.get("current_round") or 0) >= d["total_rounds"]):
            break
        if time.time() - inicio > a.limite_min * 60:
            print(f"AVISO: passou de {a.limite_min} min; a simulação segue rodando. Conferir com 'status' e 'posts'.")
            break
        time.sleep(15)
    print("Simulação concluída.", gasto_txt())


def cmd_posts(a):
    d = chamar("GET", f"/api/simulation/{a.sim}/posts?limit={a.limite}" + (f"&platform={a.plataforma}" if a.plataforma else ""))
    for p in d.get("posts", d if isinstance(d, list) else []):
        print(f"- [{p.get('user_id', '')}] {(p.get('content') or '')[:300]}")


def cmd_relatorio(a):
    r = chamar("POST", "/api/report/generate", {"simulation_id": a.sim})
    rid = r["report_id"]
    if r.get("status") != "completed":
        esperar(lambda: chamar("POST", "/api/report/generate/status", {"simulation_id": a.sim, "task_id": r.get("task_id")}),
                {"completed"}, intervalo=15, rotulo="relatório")
    rep = chamar("GET", f"/api/report/{rid}")
    saida = Path(a.saida or (REG / f"relatorio_{a.sim}.md"))
    saida.write_text(rep.get("markdown_content", ""), encoding="utf-8")
    print(f"Relatório salvo em {saida} | {gasto_txt()}")


def cmd_entrevistar(a):
    d = chamar("POST", "/api/simulation/interview", {"simulation_id": a.sim, "agent_id": a.agente,
                                                     "prompt": a.pergunta, "platform": a.plataforma}, timeout=200)
    print(json.dumps(d, ensure_ascii=False, indent=1)[:6000])
    print(gasto_txt())


def cmd_entrevistar_todos(a):
    d = chamar("POST", "/api/simulation/interview/all", {"simulation_id": a.sim, "prompt": a.pergunta,
                                                         "platform": a.plataforma}, timeout=400)
    saida = REG / f"entrevista_{a.sim}_{int(time.time())}.json"
    saida.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Respostas salvas em {saida} | {gasto_txt()}")


def cmd_chat(a):
    d = chamar("POST", "/api/report/chat", {"simulation_id": a.sim, "message": a.msg, "chat_history": []}, timeout=600)
    print(d.get("response", json.dumps(d, ensure_ascii=False)[:6000]))
    print(gasto_txt())


def cmd_fechar(a):
    print(chamar("POST", "/api/simulation/close-env", {"simulation_id": a.sim}))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for nome in ("ligar", "desligar", "status", "gasto"):
        sub.add_parser(nome)
    s = sub.add_parser("teto"); s.add_argument("usd", type=float); s.add_argument("--motivo")
    s = sub.add_parser("novo"); s.add_argument("--nome", required=True); s.add_argument("--pergunta", required=True)
    s.add_argument("--contexto"); s.add_argument("arquivos", nargs="+")
    s = sub.add_parser("reconstruir"); s.add_argument("--projeto", required=True)
    s = sub.add_parser("preparar"); s.add_argument("--projeto", required=True)
    s.add_argument("--plataforma", default="reddit", choices=["reddit", "twitter", "ambas"])
    s = sub.add_parser("perfis"); s.add_argument("--sim", required=True); s.add_argument("--plataforma")
    s = sub.add_parser("rodar"); s.add_argument("--sim", required=True); s.add_argument("--rodadas", type=int, required=True)
    s.add_argument("--plataforma", default="reddit", choices=["reddit", "twitter", "parallel"])
    s.add_argument("--inicio", type=int, default=19, help="hora simulada de início (padrão 19h, pico)")
    s.add_argument("--refazer", action="store_true", help="para e recomeça uma simulação já iniciada")
    s.add_argument("--limite-min", type=int, default=45, help="para de acompanhar após N minutos")
    s = sub.add_parser("posts"); s.add_argument("--sim", required=True); s.add_argument("--limite", type=int, default=50)
    s.add_argument("--plataforma")
    s = sub.add_parser("relatorio"); s.add_argument("--sim", required=True); s.add_argument("--saida")
    s = sub.add_parser("entrevistar"); s.add_argument("--sim", required=True); s.add_argument("--agente", type=int, required=True)
    s.add_argument("--pergunta", required=True); s.add_argument("--plataforma", default="reddit")
    s = sub.add_parser("entrevistar-todos"); s.add_argument("--sim", required=True); s.add_argument("--pergunta", required=True)
    s.add_argument("--plataforma", default="reddit")
    s = sub.add_parser("chat"); s.add_argument("--sim", required=True); s.add_argument("--msg", required=True)
    s = sub.add_parser("fechar"); s.add_argument("--sim", required=True)
    a = ap.parse_args()
    gasta = a.cmd in ("novo", "reconstruir", "preparar", "rodar", "relatorio", "entrevistar", "entrevistar-todos", "chat")
    if gasta and "DESLIGADO" in gasto_txt():
        sys.exit("ERRO: medidor desligado. Rode 'cs.py ligar' antes de qualquer etapa que gasta créditos.")
    globals()["cmd_" + a.cmd.replace("-", "_")](a)


if __name__ == "__main__":
    main()
