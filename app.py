"""
CONTROLADORIA DE PRAZOS — Dutra Bitencourt
Captura do DJEN, tratamento das publicações e geração da linha no padrão
da aba Controle de Prazos.

Como rodar:
    pip install -r requirements.txt
    streamlit run app.py

O banco é um arquivo SQLite (controladoria.db) criado ao lado do app.
"""

import html
import re
import sqlite3
from datetime import date, datetime, timedelta

import pandas as pd
import requests
import streamlit as st

API = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
DB = "controladoria.db"

OABS_PADRAO = [
    {"numero": "114155", "uf": "RS", "advogado": "Arthur Bitencourt"},
    {"numero": "524859", "uf": "SP", "advogado": "Arthur Bitencourt"},
    {"numero": "132913", "uf": "RS", "advogado": "Taís Altenhofen"},
]

RESPONSAVEIS = ["TAÍS", "LUCAS", "THOMAS", "KAMILLA", "MARIANA",
                "CAROLAINI", "MARIA LUIZA", "HANNA"]
CONTROLADORIA = ["Kamilla", "Carolaini", "Mariana"]
STATUS = ["PENDENTE", "PARA REVISAR", "PARA PROTOCOLAR", "AGUARDANDO",
          "PROTOCOLADO", "CONCLUÍDO"]
PROCEDIMENTOS = ["", "PROCEDIMENTO COMUM", "JEF", "JEC",
                 "JUIZADO DA FAZENDA PÚBLICA", "CUMPRIMENTO OU EXECUÇÃO",
                 "RECURSAL OU 2º GRAU", "ADMINISTRATIVO"]
SISTEMAS = {"TRF1": "PJE", "TRF2": "EPROC", "TRF3": "PJE", "TRF4": "EPROC",
            "TRF5": "PJE", "TRF6": "EPROC", "JFRS": "EPROC", "JFSC": "EPROC",
            "JFPR": "EPROC", "TJRS": "EPROC", "TJSC": "EPROC", "TJSP": "EPROC",
            "TJPR": "PROJUDI", "TJRR": "PROJUDI", "TJMG": "EPROC",
            "TJDFT": "PJE", "TJBA": "PJE", "TJCE": "PJE", "TJES": "PJE",
            "TJGO": "PJD", "TJMA": "PJE", "TJMT": "PJE", "TJPA": "PJE",
            "TJPI": "PJE", "TJRJ": "EPROC", "TJRO": "PJE", "TJAC": "E-SAJ",
            "STJ": "PJE", "TRT12": "PJE"}

# ----------------------------- banco -----------------------------

def conectar():
    c = sqlite3.connect(DB, check_same_thread=False)
    c.execute("""CREATE TABLE IF NOT EXISTS publicacoes (
        chave TEXT PRIMARY KEY, capturado_em TEXT, oab TEXT, advogado TEXT,
        tribunal TEXT, processo TEXT, orgao TEXT, tipo TEXT, classe TEXT,
        data_disp TEXT, teor TEXT, link TEXT, autor_sugerido TEXT,
        situacao TEXT DEFAULT 'A TRATAR', tratado_por TEXT, tratado_em TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS prazos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, chave_pub TEXT,
        data_evento TEXT, prazo INTEGER, data_final TEXT, link_bitrix TEXT,
        autor TEXT, conteudo TEXT, observacao TEXT, prazo_fatal TEXT,
        data TEXT, responsavel TEXT, status TEXT, verificacao TEXT,
        fatal_embargos TEXT, tipo_prazo TEXT, data_prevista TEXT,
        tribunal TEXT, sistema TEXT, procedimento TEXT, processo TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS suspensoes (
        de TEXT, ate TEXT, motivo TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS feriados (
        data TEXT PRIMARY KEY, descricao TEXT)""")
    return c

con = conectar()

# -------------------------- calendário --------------------------

def pascoa(a):
    b, c = a // 100, a % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * (a % 19) + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a % 19 + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    return date(a, mes, dia)

@st.cache_data(ttl=3600)
def feriados_nacionais(anos):
    d = {}
    for a in anos:
        p = pascoa(a)
        for x in [date(a, 1, 1), date(a, 4, 21), date(a, 5, 1), date(a, 9, 7),
                  date(a, 10, 12), date(a, 11, 2), date(a, 11, 15),
                  date(a, 11, 20), date(a, 12, 25), p - timedelta(48),
                  p - timedelta(47), p - timedelta(2), p + timedelta(60)]:
            d[x.isoformat()] = True
    return d

def carregar_calendario():
    anos = range(date.today().year - 1, date.today().year + 3)
    fer = dict(feriados_nacionais(tuple(anos)))
    for (dt,) in con.execute("SELECT data FROM feriados"):
        fer[dt] = True
    sus = con.execute("SELECT de, ate FROM suspensoes").fetchall()
    return fer, sus

def util(d, fer, sus, recesso=True):
    if d.weekday() >= 5:
        return False
    if d.isoformat() in fer:
        return False
    if recesso and ((d.month == 12 and d.day >= 20) or (d.month == 1 and d.day <= 20)):
        return False
    for de, ate in sus:
        if de <= d.isoformat() <= ate:
            return False
    return True

def prox_util(d, fer, sus):
    while not util(d, fer, sus):
        d += timedelta(1)
    return d

def calcular(evento: date, dias: int, fer, sus):
    """Publicação = 1º útil após a disponibilização. Início = 1º útil após a
    publicação. Fatal = N-ésimo dia útil contando o início como dia 1."""
    pub = prox_util(evento + timedelta(1), fer, sus)
    ini = prox_util(pub + timedelta(1), fer, sus)
    cur, n = ini, 1
    while n < dias:
        cur = prox_util(cur + timedelta(1), fer, sus)
        n += 1
    return pub, ini, cur

def simular(evento: date, dias: int):
    """Mesma conta do DIATRABALHO da planilha: só pula fim de semana."""
    d, faltam = evento, dias - 1
    while faltam > 0:
        d += timedelta(1)
        if d.weekday() < 5:
            faltam -= 1
    return d

# ----------------------------- DJEN -----------------------------

def limpar(t):
    t = re.sub(r"<br\s*/?>", "\n", t or "")
    t = re.sub(r"</(p|tr|div|table)>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    return re.sub(r"[ \t]{2,}", " ", t).strip()

CABECALHOS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/127.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Referer": "https://comunica.pje.jus.br/",
    "Origin": "https://comunica.pje.jus.br",
    "Connection": "keep-alive",
}

SESSAO = requests.Session()
SESSAO.headers.update(CABECALHOS)


def buscar_djen(oabs, ini, fim, por_pagina=50):
    novas, erros = 0, []
    for o in oabs:
        recusado = False
        for variante in (o["numero"], f'{o["numero"]}-O', f'{o["numero"]}-A'):
            if recusado:
                break
            pagina = 1
            while pagina <= 20:
                p = {"numeroOab": variante, "ufOab": o["uf"],
                     "dataDisponibilizacaoInicio": ini,
                     "dataDisponibilizacaoFim": fim,
                     "itensPorPagina": por_pagina, "pagina": pagina}
                try:
                    r = SESSAO.get(API, params=p, timeout=60)
                except Exception as e:
                    erros.append(f'{variante}/{o["uf"]}: falha de conexão — {e}')
                    break
                if r.status_code == 403:
                    recusado = True
                    erros.append(
                        f'{o["numero"]}/{o["uf"]}: 403 recusado pelo CNJ. '
                        "Rode o diagnostico.py na mesma máquina para "
                        "identificar a causa.")
                    break
                if r.status_code != 200:
                    erros.append(f'{variante}/{o["uf"]}: HTTP {r.status_code} — '
                                 f"{r.text[:200]}")
                    break
                try:
                    itens = r.json().get("items") or []
                except Exception:
                    erros.append(f'{variante}/{o["uf"]}: resposta não é JSON — '
                                 f"{r.text[:200]}")
                    break
                if not itens:
                    break
                for it in itens:
                    novas += gravar_publicacao(it, o)
                if len(itens) < por_pagina:
                    break
                pagina += 1
    con.commit()
    return novas, erros

def gravar_publicacao(it, oab):
    chave = str(it.get("id") or it.get("hash"))
    autor = ""
    for d in it.get("destinatarios") or []:
        nome = (d.get("nome") or "").strip()
        if d.get("polo") == "A" and nome and "SEGREDO" not in nome.upper():
            autor = nome
            break
    dados = (chave, datetime.now().isoformat(timespec="seconds"),
             f'{oab["numero"]}/{oab["uf"]}', oab["advogado"],
             it.get("siglaTribunal", ""),
             it.get("numeroprocessocommascara") or it.get("numero_processo", ""),
             it.get("nomeOrgao", ""), it.get("tipoComunicacao", ""),
             it.get("nomeClasse", ""), (it.get("data_disposicao") or
             it.get("data_disponibilizacao") or "")[:10],
             limpar(it.get("texto")), it.get("link", ""), autor)
    cur = con.execute(
        "INSERT OR IGNORE INTO publicacoes (chave,capturado_em,oab,advogado,"
        "tribunal,processo,orgao,tipo,classe,data_disp,teor,link,autor_sugerido)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", dados)
    return cur.rowcount

# ------------------------------ UI ------------------------------

st.set_page_config(page_title="Controladoria de prazos", layout="wide")
fer, sus = carregar_calendario()

st.sidebar.title("Controladoria")
usuario = st.sidebar.selectbox("Conferido por", ["", *CONTROLADORIA],
                               help="Quem está tratando as publicações agora. "
                                    "Vai para a coluna de verificação da "
                                    "controladoria em cada linha lançada.")
aba = st.sidebar.radio("", ["Publicações a tratar", "Prazos", "Calendário"])

with st.sidebar.expander("Buscar no DJEN"):
    dias_tras = st.number_input("Dias retroativos", 1, 30, 3)
    if st.button("Buscar agora"):
        if not usuario:
            st.warning("Identifique-se antes de capturar.")
        else:
            fim = date.today()
            ini = fim - timedelta(int(dias_tras))
            with st.spinner("Consultando o DJEN…"):
                n, erros = buscar_djen(OABS_PADRAO, ini.isoformat(), fim.isoformat())
            st.success(f"{n} publicações novas.")
            for e in erros:
                st.error(e)

# ---------------------- publicações a tratar ----------------------

if aba == "Publicações a tratar":
    pend = pd.read_sql(
        "SELECT * FROM publicacoes WHERE situacao='A TRATAR' ORDER BY data_disp", con)
    st.subheader(f"{len(pend)} publicações aguardando tratamento")
    if pend.empty:
        st.info("Nada na fila. Use Buscar no DJEN na barra lateral.")
    else:
        p = pend.iloc[0]
        c1, c2 = st.columns([3, 2])
        with c1:
            st.caption(f'{p.tribunal} · {p.orgao} · {p.tipo} · {p.classe}')
            st.markdown(f"**{p.processo}** — disponibilizada em {p.data_disp}")
            st.markdown(f"Intimação dirigida a **{p.advogado}** (OAB {p.oab})")
            if p.link:
                st.markdown(f"[Abrir no tribunal]({p.link})")
            st.text_area("Teor", p.teor, height=380, key="teor")
        with c2:
            tipo_prazo = st.radio("Tipo", ["ABERTO", "A ABRIR"], horizontal=True)
            autor = st.text_input("Autor", p.autor_sugerido)
            conteudo = st.text_input("Conteúdo do prazo")
            evento = st.date_input(
                "Data do evento", date.fromisoformat(p.data_disp) if p.data_disp else date.today())
            if tipo_prazo == "ABERTO":
                dias = st.number_input("Prazo em dias", 1, 120, 15)
                prevista = None
            else:
                dias = 0
                prevista = st.date_input("Data prevista", date.today())
            col = st.columns(2)
            tribunal = col[0].text_input("Tribunal", p.tribunal)
            sistema = col[1].selectbox(
                "Sistema", sorted(set(SISTEMAS.values()) | {""}),
                index=sorted(set(SISTEMAS.values()) | {""}).index(
                    SISTEMAS.get(p.tribunal, "")))
            procedimento = st.selectbox("Procedimento", PROCEDIMENTOS)
            col2 = st.columns(2)
            responsavel = col2[0].selectbox("Responsável", RESPONSAVEIS)
            status = col2[1].selectbox("Status", STATUS)
            link_bitrix = st.text_input("Link do Bitrix")
            obs = st.text_area("Observação", height=68)
            embargos = st.checkbox("Gerar também fatal de embargos (5 dias úteis)")

            if tipo_prazo == "ABERTO" and dias:
                pub, ini_c, fatal = calcular(evento, int(dias), fer, sus)
                sim = simular(evento, int(dias))
                st.info(
                    f"Data final (simulação, como na planilha): **{sim:%d/%m/%Y}**\n\n"
                    f"Publicação {pub:%d/%m/%Y} · início {ini_c:%d/%m/%Y}\n\n"
                    f"Fatal real (feriados, recesso e suspensões): **{fatal:%d/%m/%Y}**")
                if sim != fatal:
                    st.warning("Simulação e fatal divergem: há feriado, recesso "
                               "ou suspensão no período. Confira.")
            else:
                fatal = sim = None
                st.info("Evento previsto: sem contagem. O fatal fica como AGUARDA.")

            if st.button("Lançar", type="primary", disabled=not (usuario and autor)):
                emb = calcular(evento, 5, fer, sus)[2] if (embargos and tipo_prazo == "ABERTO") else None
                con.execute(
                    "INSERT INTO prazos (chave_pub,data_evento,prazo,data_final,"
                    "link_bitrix,autor,conteudo,observacao,prazo_fatal,data,"
                    "responsavel,status,verificacao,fatal_embargos,tipo_prazo,"
                    "data_prevista,tribunal,sistema,procedimento,processo)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (p.chave, evento.isoformat(), int(dias) or None,
                     sim.isoformat() if sim else None, link_bitrix,
                     autor.upper(), conteudo.upper(), obs,
                     fatal.isoformat() if fatal else "AGUARDA",
                     date.today().isoformat(), responsavel, status, usuario,
                     emb.isoformat() if emb else None, tipo_prazo,
                     prevista.isoformat() if prevista else None,
                     tribunal.upper(), sistema, procedimento, p.processo))
                con.execute("UPDATE publicacoes SET situacao='TRATADA',"
                            " tratado_por=?, tratado_em=? WHERE chave=?",
                            (usuario, datetime.now().isoformat(timespec="seconds"), p.chave))
                con.commit()
                st.rerun()

            if st.button("Descartar (sem prazo)", disabled=not usuario):
                con.execute("UPDATE publicacoes SET situacao='DESCARTADA',"
                            " tratado_por=?, tratado_em=? WHERE chave=?",
                            (usuario, datetime.now().isoformat(timespec="seconds"), p.chave))
                con.commit()
                st.rerun()

# ------------------------------ prazos ------------------------------

elif aba == "Prazos":
    df = pd.read_sql("SELECT * FROM prazos ORDER BY prazo_fatal", con)
    st.subheader("Prazos lançados")
    if df.empty:
        st.info("Nenhum prazo lançado ainda.")
    else:
        hoje = date.today().isoformat()
        abertos = df[(df.status != "PROTOCOLADO") & (df.prazo_fatal != "AGUARDA")]
        c = st.columns(4)
        c[0].metric("Fatal vencido", int((abertos.prazo_fatal < hoje).sum()))
        c[1].metric("Fatal hoje", int((abertos.prazo_fatal == hoje).sum()))
        c[2].metric("Aguardando abertura", int((df.tipo_prazo == "A ABRIR").sum()))
        c[3].metric("Protocolados", int((df.status == "PROTOCOLADO").sum()))
        st.dataframe(df, use_container_width=True, hide_index=True)
        colunas = ["DATA EVENTO", "PRAZO", "DATA FINAL", "LINK BITRIX", "AUTOR",
                   "CONTEÚDO DO PRAZO", "OBSERVAÇÃO", "PRAZO FATAL", "DATA",
                   "RESPONSÁVEL", "STATUS", "VERIFICAÇÃO CONTROLADORIA",
                   "FATAL EMBARGOS", "TIPO DE PRAZO", "DATA PREVISTA",
                   "TRIBUNAL", "SISTEMA", "PROCEDIMENTO", "PROCESSO"]
        exp = df[["data_evento", "prazo", "data_final", "link_bitrix", "autor",
                  "conteudo", "observacao", "prazo_fatal", "data", "responsavel",
                  "status", "verificacao", "fatal_embargos", "tipo_prazo",
                  "data_prevista", "tribunal", "sistema", "procedimento",
                  "processo"]]
        exp.columns = colunas
        st.download_button("Baixar CSV no formato da planilha",
                           exp.to_csv(index=False, sep=";").encode("utf-8-sig"),
                           f"prazos-{date.today()}.csv", "text/csv")

# ---------------------------- calendário ----------------------------

else:
    st.subheader("Feriados locais e suspensões")
    st.caption("Os feriados nacionais já vêm calculados, inclusive os móveis. "
               "Feriado estadual, municipal e suspensão por portaria precisam "
               "ser cadastrados aqui, senão o fatal erra.")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Feriado local**")
        d = st.date_input("Data", key="fd")
        desc = st.text_input("Descrição", key="fdesc")
        if st.button("Incluir feriado") and desc:
            con.execute("INSERT OR REPLACE INTO feriados VALUES (?,?)",
                        (d.isoformat(), desc))
            con.commit()
            st.cache_data.clear()
            st.rerun()
        st.dataframe(pd.read_sql("SELECT * FROM feriados ORDER BY data", con),
                     hide_index=True, use_container_width=True)
    with c2:
        st.markdown("**Suspensão**")
        de = st.date_input("De", key="sde")
        ate = st.date_input("Até", key="sate")
        motivo = st.text_input("Motivo (portaria)", key="smot")
        if st.button("Incluir suspensão") and motivo:
            con.execute("INSERT INTO suspensoes VALUES (?,?,?)",
                        (de.isoformat(), ate.isoformat(), motivo))
            con.commit()
            st.rerun()
        st.dataframe(pd.read_sql("SELECT * FROM suspensoes ORDER BY de", con),
                     hide_index=True, use_container_width=True)
