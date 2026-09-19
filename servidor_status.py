"""
servidor_status.py
==================
Serviço HTTP somente leitura na porta 8000 (a "porta do serviço" do grupo de
segurança). Publica os resultados do benchmark para a equipe acompanhar sem
abrir sessão SSH. Não executa nada, não recebe upload: só lê JSON.

Rotas:
    GET /           página com o resumo do benchmark
    GET /resultado  benchmark_resultado.json bruto
    GET /tabela     tabela_speedup.md (texto para colar no relatório)
    GET /saude      {"status": "ok", ...}

Uso (na EC2):
    python servidor_status.py --porta 8000
"""

import argparse
import html
import json
import os
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

AQUI = Path(__file__).resolve().parent
ARQUIVO = AQUI / "benchmark_resultado.json"


def carregar():
    try:
        return json.loads(ARQUIVO.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


class Handler(BaseHTTPRequestHandler):
    def _enviar(self, codigo, corpo, tipo):
        dados = corpo.encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", f"{tipo}; charset=utf-8")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def do_GET(self):
        if self.path == "/saude":
            info = {"status": "ok", "host": socket.gethostname(), "vcpus": os.cpu_count()}
            return self._enviar(200, json.dumps(info), "application/json")
        if self.path == "/tabela":
            md = AQUI / "tabela_speedup.md"
            if not md.exists():
                return self._enviar(404, "rode python relatorio_speedup.py antes", "text/plain")
            return self._enviar(200, md.read_text(encoding="utf-8"), "text/plain")
        d = carregar()
        if self.path == "/resultado":
            if d is None:
                return self._enviar(404, '{"erro": "benchmark ainda não executado"}', "application/json")
            return self._enviar(200, json.dumps(d, indent=2, ensure_ascii=False), "application/json")
        if self.path != "/":
            return self._enviar(404, "não encontrado", "text/plain")

        if d is None:
            corpo = "<p>Benchmark ainda não executado.</p>"
        else:
            linhas = "".join(
                f"<tr><td>{i}</td><td>{s:.2f}</td><td>{p:.2f}</td><td>{s / p:.2f}x</td></tr>"
                for i, (s, p) in enumerate(zip(d["tempos_seq_s"], d["tempos_par_s"]), 1)
            )
            corpo = f"""
            <p>{d['workers']} processos | {d['total_imagens']} imagens | host {html.escape(socket.gethostname())}</p>
            <table border=1 cellpadding=6>
              <tr><th>Rep</th><th>Sequencial (s)</th><th>Paralelo (s)</th><th>Speedup</th></tr>
              {linhas}
            </table>
            <p><b>Speedup médio:</b> {d['speedup_medido']:.2f}x |
               <b>Amdahl (p medido = {d['p_medido']:.3f}):</b> {d['speedup_amdahl_p_medido']:.2f}x |
               <b>Amdahl (p ficha = {d['p_ficha']}):</b> {d['speedup_amdahl_p_ficha']:.2f}x</p>
            <p><a href="/tabela">Tabela e análise para o relatório</a> | <a href="/resultado">JSON completo</a></p>"""
        pagina = f"<html><head><title>Benchmark Etapa 1</title></head><body><h1>Benchmark Etapa 1</h1>{corpo}</body></html>"
        self._enviar(200, pagina, "text/html")

    def log_message(self, fmt, *args):
        print(f"{self.client_address[0]} {fmt % args}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--porta", type=int, default=8000)
    args = parser.parse_args()
    print(f"Servindo status em 0.0.0.0:{args.porta} (acesso limitado pelo grupo de segurança)")
    ThreadingHTTPServer(("0.0.0.0", args.porta), Handler).serve_forever()


if __name__ == "__main__":
    main()
