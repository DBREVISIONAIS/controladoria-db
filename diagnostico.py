"""
Diagnóstico do 403 na API do DJEN.

Rode na mesma máquina e no mesmo momento em que a busca falha:
    python diagnostico.py

Ele tenta a mesma consulta de várias formas e mostra o código de cada uma.
Me mande a saída inteira.
"""

import requests

API = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
PARAMS = {
    "numeroOab": "114155",
    "ufOab": "RS",
    "dataDisponibilizacaoInicio": "2026-09-03",
    "dataDisponibilizacaoFim": "2026-09-10",
    "itensPorPagina": 5,
    "pagina": 1,
}

CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36")

TENTATIVAS = [
    ("1. requests puro, sem nenhum cabeçalho", {}),
    ("2. só User-Agent do Chrome", {"User-Agent": CHROME}),
    ("3. User-Agent + Accept", {"User-Agent": CHROME,
                                "Accept": "application/json"}),
    ("4. tudo, incluindo Origin e Referer", {
        "User-Agent": CHROME,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9",
        "Referer": "https://comunica.pje.jus.br/",
        "Origin": "https://comunica.pje.jus.br",
    }),
]


def rodar():
    print("Testando", API, "\n")
    for nome, headers in TENTATIVAS:
        try:
            r = requests.get(API, params=PARAMS, headers=headers, timeout=60)
            corpo = r.text[:180].replace("\n", " ")
            print(f"{nome}\n   HTTP {r.status_code} — {corpo}\n")
        except Exception as e:
            print(f"{nome}\n   falha de conexão: {e}\n")

    # Bloqueio por impressão digital de TLS: o filtro identifica que o cliente
    # é Python mesmo com o cabeçalho de Chrome. curl_cffi imita o Chrome.
    try:
        from curl_cffi import requests as cf
        r = cf.get(API, params=PARAMS, impersonate="chrome", timeout=60)
        print(f"5. curl_cffi imitando Chrome\n   HTTP {r.status_code} — "
              f"{r.text[:180]}\n")
    except ImportError:
        print("5. curl_cffi não instalado. Para testar esta hipótese:\n"
              "   pip install curl_cffi   e rode o diagnóstico de novo\n")
    except Exception as e:
        print(f"5. curl_cffi\n   falha: {e}\n")

    print("Qual é o seu IP de saída (o CNJ pode estar bloqueando a rede):")
    try:
        print("  ", requests.get("https://api.ipify.org", timeout=20).text)
    except Exception as e:
        print("   não consegui verificar:", e)


if __name__ == "__main__":
    rodar()
