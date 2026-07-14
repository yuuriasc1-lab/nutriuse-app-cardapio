# -*- coding: utf-8 -*-
"""
app.py — App Cardápio (MVP): Copiloto Clínico de Prescrição Dietética
=====================================================================

Fluxo automatizado (Humano no Loop):
    1. A nutricionista COLA a anamnese (texto livre).
    2. A IA (Google Gemini) LÊ e extrai os dados estruturados.
    3. A nutricionista REVISA/AJUSTA dados, meta calórica e macros.
    4. O motor GERA o cardápio a partir das metas aprovadas (escala por macro + swaps).
    5. Saída na tela + EXPORT em texto/Markdown para copiar no WebDiet.

Execução:
    pip install streamlit google-genai
    streamlit run app.py

Módulos:
    motor.py        -> cálculo clínico + geração do cardápio (lógica pura)
    anamnese_ia.py  -> leitura da anamnese via IA
"""

import streamlit as st

import design_marcela

import motor
import anamnese_ia
import comando_ia
import converter_cardapio as conv  # reusa o resolver de macros (sem efeitos no import)
import preparos
import regras_clinicas
import revisor_cardapio


# ---------------------------------------------------------------------------
# Config + cache de dados
# ---------------------------------------------------------------------------

st.set_page_config(page_title="App Cardápio — Copiloto Clínico", page_icon="🥗", layout="wide")

FATORES_ATIVIDADE = {
    "Sedentário — 1.2": 1.2,
    "Leve (1-3x/sem) — 1.375": 1.375,
    "Moderado (3-5x/sem) — 1.55": 1.55,
    "Intenso (6-7x/sem) — 1.725": 1.725,
    "Atleta — 1.9": 1.9,
}

META_KCAL_MIN = 800
META_KCAL_MAX = 5000
META_KCAL_STEP = 25

REVISAO_WIDGET_KEYS = (
    "rev_idade", "rev_peso", "rev_altura", "rev_genero", "rev_objetivo",
    "rev_faf", "rev_aversoes", "rev_alergias", "rev_intolerancias",
    "rev_preferencias", "rev_patologias", "rev_medicamentos",
    "rev_exames_obs", "rev_meta_kcal", "rev_prot_kg", "rev_perc_gord",
)


@st.cache_data(show_spinner=False)
def _carregar_dados():
    return motor.carregar_template(), motor.carregar_banco_alimentos()


@st.cache_resource(show_spinner=False)
def _recursos_resolver():
    """Carrega (1x) os recursos do resolver de macros reusado do conversor."""
    return (conv.carregar_curados_por_100g(), conv.carregar_indice_tbca(),
            conv.carregar_medidas_ref())


@st.cache_data(show_spinner=False)
def _carregar_regras_clinicas():
    return regras_clinicas.carregar_regras()


@st.cache_data(show_spinner=False)
def _carregar_preparos_curados():
    return preparos.carregar_preparos()


def _resolver_alimento(nome, gramas):
    """Resolve macros de um alimento (nome, gramas) via o mesmo resolver do
    conversor, e anexa a medida caseira de referência se houver."""
    curados, indice, medref = _recursos_resolver()
    al, _conf = conv.resolver_macros(nome, gramas, False, curados, indice)
    if not al.get("medida_unidade"):
        un, gpu = conv.medida_de_referencia(nome, medref)
        al["medida_unidade"], al["gramas_por_unidade"] = un, gpu
    return al


def _faf_para_rotulo(valor):
    """Mapeia um FAF numérico para o rótulo mais próximo do selectbox."""
    if not valor:
        return "Moderado (3-5x/sem) — 1.55"
    melhor = min(FATORES_ATIVIDADE.items(), key=lambda kv: abs(kv[1] - float(valor)))
    return melhor[0]


def _clamp_int(valor, minimo, maximo):
    return int(max(minimo, min(maximo, round(float(valor)))))


def _resetar_controles_revisao():
    for chave in REVISAO_WIDGET_KEYS:
        st.session_state.pop(chave, None)


# ---------------------------------------------------------------------------
# Estado da sessão
# ---------------------------------------------------------------------------

def _init_estado():
    st.session_state.setdefault("anamnese", None)   # dict extraído/editado
    st.session_state.setdefault("resultado", None)  # cardápio gerado
    st.session_state.setdefault("trocas", {})       # {(si, oi, fi): {escolha, pick}}
    st.session_state.setdefault("adicoes", {})      # {(si, oi): [alimento, ...]} (via comando)
    st.session_state.setdefault("ajustes", {})      # {(si, oi, fi): gramas_alvo} (via comando)
    st.session_state.setdefault("comando_plano", None)  # plano pendente de confirmação
    st.session_state.setdefault("preparos_ia", {})  # {nome_refeicao: preparo_ia}


# ---------------------------------------------------------------------------
# Sidebar — configuração da IA
# ---------------------------------------------------------------------------

def _sidebar_ia():
    design_marcela.sidebar_brand()
    st.sidebar.header("⚙️ Configuração")
    st.sidebar.markdown("**Leitura da anamnese por IA**")
    # Lê a chave salva em .streamlit/secrets.toml, se existir (sem quebrar se não).
    try:
        chave_salva = st.secrets.get("GEMINI_API_KEY", "")
        if chave_salva == "COLE_SUA_CHAVE_AQUI":
            chave_salva = ""
    except Exception:
        chave_salva = ""

    api_key = st.sidebar.text_input(
        "Chave da API Gemini",
        type="password",
        help="Gratuita em https://aistudio.google.com/apikey — cobre dezenas de "
             "cardápios/mês. Sem a chave, é possível preencher manualmente.",
        value=chave_salva,
    )
    modelo = st.sidebar.selectbox(
        "Modelo",
        ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.5-pro"],
        help="Flash é gratuito e suficiente. Pro é mais preciso (e mais lento).",
    )
    st.sidebar.caption("🔒 A chave fica só nesta sessão do navegador.")
    return api_key, modelo


# ---------------------------------------------------------------------------
# Etapa 1 — Colar anamnese + extrair
# ---------------------------------------------------------------------------

def _etapa_anamnese(api_key, modelo):
    st.subheader("1️⃣ Anamnese do Paciente")
    st.caption("Cole a anamnese preenchida. A IA lê e preenche os campos abaixo "
               "para você revisar.")

    texto = st.text_area(
        "Texto da anamnese",
        height=240,
        placeholder="Cole aqui o prontuário/anamnese (peso, objetivo, atividade "
                    "física, aversões, patologias, rotina alimentar, etc.)",
    )

    col1, col2 = st.columns([1, 1])
    with col1:
        ler = st.button("🤖 Ler anamnese com IA", width="stretch", type="primary")
    with col2:
        manual = st.button("✍️ Preencher manualmente (sem IA)", width="stretch")

    if ler:
        if not texto.strip():
            st.warning("Cole o texto da anamnese antes de ler.")
        else:
            try:
                with st.spinner("Lendo a anamnese..."):
                    st.session_state.anamnese = anamnese_ia.extrair_anamnese(
                        texto, api_key=api_key, modelo=modelo
                    )
                st.session_state.resultado = None
                _resetar_controles_revisao()
                st.success("Anamnese lida! Revise os dados abaixo. 👇")
            except anamnese_ia.ConfiguracaoIAError as e:
                st.error(f"❌ {e}")
                st.info("Você pode preencher manualmente clicando no botão ao lado.")
            except Exception as e:  # rede, JSON inválido, etc.
                st.error(f"❌ Falha ao ler a anamnese: {e}")

    if manual:
        st.session_state.anamnese = anamnese_ia.anamnese_vazia()
        st.session_state.resultado = None
        _resetar_controles_revisao()
        st.info("Formulário em branco pronto para preenchimento.")


# ---------------------------------------------------------------------------
# Etapa 2 — Revisar/ajustar dados + parâmetros clínicos
# ---------------------------------------------------------------------------

def _etapa_revisao():
    a = st.session_state.anamnese
    if a is None:
        return None

    st.divider()
    st.subheader("2️⃣ Revisão, metas e parâmetros clínicos")
    st.caption(
        "Confira a anamnese, defina a meta calórica final e ajuste os macros antes "
        "de gerar o cardápio."
    )

    st.markdown("**Dados antropométricos**")
    c1, c2, c3, c4 = st.columns(4)
    idade = c1.number_input(
        "Idade", 1, 120, int(a.get("idade") or 30), key="rev_idade"
    )
    peso = c2.number_input(
        "Peso (kg)", 20.0, 300.0, float(a.get("peso_atual_kg") or 70.0),
        step=0.5, key="rev_peso",
    )
    altura = c3.number_input(
        "Altura (cm)", 100.0, 230.0, float(a.get("altura_cm") or 170.0),
        step=0.5, key="rev_altura",
    )
    genero_idx = 0 if motor.normalizar_texto(a.get("genero")) != "feminino" else 1
    genero = c4.selectbox(
        "Gênero", ["Masculino", "Feminino"], index=genero_idx, key="rev_genero"
    )

    st.markdown("**Objetivo e atividade**")
    c5, c6 = st.columns(2)
    objetivos = ["Emagrecimento", "Manutenção", "Hipertrofia"]
    obj_atual = a.get("objetivo") if a.get("objetivo") in objetivos else "Emagrecimento"
    objetivo = c5.selectbox(
        "Objetivo clínico", objetivos, index=objetivos.index(obj_atual),
        key="rev_objetivo",
    )
    rotulo_faf = _faf_para_rotulo(a.get("fator_atividade"))
    faf_label = c6.selectbox(
        "Fator de atividade", list(FATORES_ATIVIDADE.keys()),
        index=list(FATORES_ATIVIDADE).index(rotulo_faf), key="rev_faf",
    )
    faf = FATORES_ATIVIDADE[faf_label]

    metas_sugeridas = motor.calcular_metas(
        peso_kg=peso, altura_cm=altura, idade=idade, genero=genero,
        fator_atividade=faf, objetivo=objetivo,
    )

    st.markdown("**Metas antes da geração**")
    st.caption(
        "TMB e GET ficam como referência. A geração usa a meta calórica final "
        "definida pela Marcela."
    )
    meta_padrao = _clamp_int(metas_sugeridas["meta_kcal"], META_KCAL_MIN, META_KCAL_MAX)
    prot_padrao = float(motor.PROTEINA_G_KG_PADRAO.get(objetivo, 1.6))
    gordura_padrao = int(motor.PERC_GORDURA_PADRAO * 100)

    mc1, mc2, mc3 = st.columns(3)
    meta_kcal = mc1.slider(
        "Meta calórica final (kcal)", META_KCAL_MIN, META_KCAL_MAX,
        meta_padrao, step=META_KCAL_STEP, key="rev_meta_kcal",
        help="Valor final definido pela nutricionista para gerar o cardápio.",
    )
    prot_kg = mc2.slider(
        "Proteína (g/kg)", 0.5, 3.5, prot_padrao, step=0.1, key="rev_prot_kg",
    )
    perc_gord_pct = mc3.slider(
        "Gordura (% kcal)", 15, 40, gordura_padrao, step=1, key="rev_perc_gord",
    )
    perc_gord = perc_gord_pct / 100.0

    metas = motor.calcular_metas(
        peso_kg=peso, altura_cm=altura, idade=idade, genero=genero,
        fator_atividade=faf, objetivo=objetivo, prot_g_kg=prot_kg,
        perc_gordura=perc_gord, meta_kcal_manual=meta_kcal,
    )

    r1, r2, r3, r4 = st.columns(4)
    r1.metric("TMB de referência", f"{metas['tmb']} kcal")
    r2.metric("GET de referência", f"{metas['get']} kcal")
    r3.metric("Meta definida", f"{metas['meta_kcal']} kcal")
    r4.metric("Ajuste vs GET", f"{metas['ajuste_kcal']:+d} kcal")
    r5, r6, r7, r8 = st.columns(4)
    r5.metric("Proteína", f"{metas['meta_prot_g']:.0f} g", help=f"{prot_kg:.1f} g/kg")
    r6.metric("Gordura", f"{metas['meta_gord_g']:.0f} g", help=f"{perc_gord_pct}% kcal")
    r7.metric("Carboidrato", f"{metas['meta_carb_g']:.0f} g")
    r8.metric("Fibra alvo", f"{metas['meta_fibra_g']:.0f} g")
    if metas["meta_carb_g"] <= 0:
        st.warning(
            "A combinação atual de meta calórica, proteína e gordura não deixa "
            "calorias disponíveis para carboidratos. Ajuste antes de gerar."
        )

    st.markdown("**Filtros alimentares** (separe por vírgula)")
    c7, c8 = st.columns(2)
    aversoes = c7.text_input(
        "Aversões", ", ".join(a.get("aversoes", [])), key="rev_aversoes"
    )
    alergias = c7.text_input(
        "Alergias", ", ".join(a.get("alergias", [])), key="rev_alergias"
    )
    intolerancias = c8.text_input(
        "Intolerâncias", ", ".join(a.get("intolerancias", [])),
        key="rev_intolerancias",
    )
    preferencias = c8.text_input(
        "Preferências (inegociáveis)", ", ".join(a.get("preferencias", [])),
        key="rev_preferencias",
    )

    with st.expander("🩺 Dados clínicos para regras de revisão"):
        cd1, cd2 = st.columns(2)
        patologias_txt = cd1.text_input(
            "Patologias", ", ".join(a.get("patologias", [])), key="rev_patologias"
        )
        medicamentos_txt = cd2.text_input(
            "Medicamentos", ", ".join(a.get("medicamentos", [])),
            key="rev_medicamentos",
        )
        exames_obs = st.text_area(
            "Exames / observações clínicas",
            value=a.get("exames_observacoes") or "",
            height=90,
            placeholder="Ex.: glicemia alterada, creatinina alta, colesterol, pressão alta...",
            key="rev_exames_obs",
        )

    anamnese_revisada = _montar_anamnese_revisada(
        a, patologias_txt, medicamentos_txt, exames_obs,
        aversoes, alergias, intolerancias, preferencias,
    )
    regras_ativas = regras_clinicas.avaliar_anamnese(
        anamnese_revisada, _carregar_regras_clinicas()
    )
    termos_regras = regras_clinicas.termos_exclusao(anamnese_revisada, regras_ativas)
    if regras_ativas:
        with st.expander("⚠️ Regras clínicas detectadas", expanded=True):
            for regra in regras_clinicas.resumo_regras(regras_ativas):
                st.markdown(
                    f"**{regra['titulo']}** · {regra['severidade']}  \n"
                    f"{regra['mensagem']}"
                )
            if termos_regras:
                st.caption(
                    "Termos adicionados aos filtros alimentares: "
                    + ", ".join(termos_regras)
                )
    else:
        st.caption("Nenhuma regra clínica específica detectada nos dados informados.")

    excluidos_usuario = _juntar_termos(aversoes, alergias, intolerancias)
    excluidos = _unicos(excluidos_usuario + termos_regras)
    assinatura_revisao = (
        int(idade), round(float(peso), 1), round(float(altura), 1), genero,
        objetivo, round(float(faf), 3), int(meta_kcal), round(float(prot_kg), 2),
        round(float(perc_gord), 3),
        tuple(motor.normalizar_texto(t) for t in excluidos),
        tuple(r.get("id", "") for r in regras_ativas),
    )
    resultado_atual = st.session_state.get("resultado")
    if resultado_atual and resultado_atual.get("assinatura_revisao") != assinatura_revisao:
        st.session_state.resultado = None
        st.session_state.trocas = {}
        st.session_state.adicoes = {}
        st.session_state.ajustes = {}
        st.session_state.comando_plano = None
        st.session_state.preparos_ia = {}
        st.info("Metas ou filtros alterados. Gere o cardápio novamente para aplicar.")

    gerar = st.button(
        "🍽️ Gerar Cardápio com estas metas", type="primary", width="stretch",
        disabled=metas["meta_carb_g"] <= 0,
    )

    if gerar:
        return {
            "idade": idade, "peso": peso, "altura": altura, "genero": genero,
            "objetivo": objetivo, "faf": faf,
            "meta_kcal": meta_kcal, "prot_kg": prot_kg, "perc_gord": perc_gord,
            "metas": metas,
            "assinatura_revisao": assinatura_revisao,
            "excluidos": excluidos,
            "excluidos_usuario": excluidos_usuario,
            "excluidos_regras": termos_regras,
            "anamnese": anamnese_revisada,
            "regras_ativas": regras_ativas,
        }
    return None


def _juntar_termos(*campos):
    termos = []
    for campo in campos:
        termos += [t.strip() for t in (campo or "").split(",") if t.strip()]
    return termos


def _unicos(termos):
    vistos = set()
    resultado = []
    for termo in termos:
        chave = motor.normalizar_texto(termo)
        if not chave or chave in vistos:
            continue
        vistos.add(chave)
        resultado.append(str(termo).strip())
    return resultado


def _montar_anamnese_revisada(base, patologias, medicamentos, exames,
                              aversoes, alergias, intolerancias, preferencias):
    revisada = dict(base or {})
    revisada["patologias"] = _juntar_termos(patologias)
    revisada["medicamentos"] = _juntar_termos(medicamentos)
    revisada["exames_observacoes"] = exames
    revisada["aversoes"] = _juntar_termos(aversoes)
    revisada["alergias"] = _juntar_termos(alergias)
    revisada["intolerancias"] = _juntar_termos(intolerancias)
    revisada["preferencias"] = _juntar_termos(preferencias)
    return revisada


# ---------------------------------------------------------------------------
# Etapa 3 — Gerar + exibir
# ---------------------------------------------------------------------------

def _gerar(template, banco, params):
    metas = params.get("metas")
    if metas is None:
        metas = motor.calcular_metas(
            peso_kg=params["peso"], altura_cm=params["altura"], idade=params["idade"],
            genero=params["genero"], fator_atividade=params["faf"], objetivo=params["objetivo"],
            prot_g_kg=params["prot_kg"], perc_gordura=params["perc_gord"],
            meta_kcal_manual=params.get("meta_kcal"),
        )
    slots, totais, fatores, avisos = motor.gerar_cardapio(
        template, banco, metas, params["excluidos"]
    )
    st.session_state.resultado = {
        "metas": metas, "slots": slots, "totais": totais, "fatores": fatores,
        "avisos": avisos, "excluidos": params["excluidos"],
        "assinatura_revisao": params.get("assinatura_revisao"),
        "excluidos_usuario": params.get("excluidos_usuario", []),
        "excluidos_regras": params.get("excluidos_regras", []),
        "anamnese": params.get("anamnese", {}),
        "regras_ativas": params.get("regras_ativas", []),
    }
    st.session_state.trocas = {}        # zera trocas ao gerar um cardápio novo
    st.session_state.adicoes = {}       # idem para adições via comando
    st.session_state.ajustes = {}       # idem para ajustes de quantidade/macro
    st.session_state.comando_plano = None
    st.session_state.preparos_ia = {}


def _exibir_resumo(metas):
    st.subheader("📊 Resumo Clínico e Metas")
    c1, c2, c3 = st.columns(3)
    c1.metric("TMB (Mifflin-St Jeor)", f"{metas['tmb']} kcal")
    c2.metric("GET", f"{metas['get']} kcal")
    c3.metric("Meta calórica definida", f"{metas['meta_kcal']} kcal",
              delta=f"{metas['ajuste_kcal']:+d} kcal vs GET")
    c4, c5, c6, c7 = st.columns(4)
    c4.metric("Proteína", f"{metas['meta_prot_g']:.0f} g", help=f"{metas['prot_g_kg']} g/kg")
    c5.metric("Gordura", f"{metas['meta_gord_g']:.0f} g", help=f"{metas['perc_gordura']*100:.0f}% kcal")
    c6.metric("Carboidrato", f"{metas['meta_carb_g']:.0f} g")
    c7.metric("Fibra (alvo)", f"{metas['meta_fibra_g']:.0f} g")


def _exibir_validacao(metas, slots, totais):
    """Painel automático que confere os cálculos do cardápio (já com trocas)."""
    v = motor.validar_resultado(slots, totais, metas)
    st.subheader("✅ Validação dos Cálculos")

    c1, c2 = st.columns(2)
    c1.success("Fórmulas conferidas: TMB/GET de referência → metas de macro.")
    if v["somas_ok"]:
        c2.success("Somas das refeições batem com os totais.")
    else:
        c2.error("Inconsistência na soma das refeições — revisar.")

    if not v["incoerentes"]:
        st.success(f"Todos os {v['n_alimentos']} alimentos com valores nutricionais "
                   f"coerentes (calorias ≈ 4×carbo + 4×prot + 9×gordura).")
    else:
        st.warning(f"⚠️ {len(v['incoerentes'])} alimento(s) com valores a revisar "
                   f"(calorias não fecham com os macros):")
        st.dataframe(
            [{"Alimento": i["nome"], "Kcal informada": i["kcal"],
              "Kcal pelos macros": i["atwater"], "Desvio %": i["pct"]}
             for i in v["incoerentes"]],
            hide_index=True, width="stretch",
        )

    # Aderência às metas (verde se perto, amarelo se distante).
    st.markdown("**Aderência às metas**")
    cols = st.columns(4)
    rotulos = [("kcal", "Calorias", "kcal"), ("carboidratos_g", "Carboidrato", "g"),
               ("proteinas_g", "Proteína", "g"), ("gorduras_g", "Gordura", "g")]
    for col, (chave, titulo, un) in zip(cols, rotulos):
        d = v["desvios"][chave]
        col.metric(titulo, f"{d['atingido']:.0f} {un}",
                   delta=f"{d['pct']:+d}% vs meta")
    st.caption("Proteína e carboidrato são ancorados às metas; a gordura é "
               "reportada (ajuste o % de gordura ou inclua azeite/oleaginosas se "
               "o desvio incomodar).")


def _exibir_revisao_clinica(resultado, working_slots, totais):
    st.subheader("🩺 Revisão Clínica")
    regras = resultado.get("regras_ativas", [])
    if regras:
        for regra in regras_clinicas.resumo_regras(regras):
            st.info(f"**{regra['titulo']}** · {regra['severidade']} — {regra['mensagem']}")
    else:
        st.caption("Nenhuma regra clínica específica detectada para esta anamnese.")

    revisao = revisor_cardapio.revisar_cardapio(
        resultado["metas"],
        working_slots,
        totais,
        resultado.get("anamnese", {}),
        regras_ativas=regras,
    )
    alertas = revisao["alertas"]
    if not alertas:
        st.success("Nenhum alerta clínico adicional encontrado no cardápio principal.")
        return

    st.warning(f"{len(alertas)} ponto(s) para revisão antes da entrega.")
    for alerta in alertas[:12]:
        texto = f"**{alerta['titulo']}** · {alerta['severidade']}  \n{alerta['descricao']}"
        if alerta["severidade"] == "critica":
            st.error(texto)
        elif alerta["severidade"] == "alta":
            st.warning(texto)
        else:
            st.info(texto)


# ---------------------------------------------------------------------------
# Substituição interativa de alimentos
# ---------------------------------------------------------------------------

MANTER = "Manter o original"
TBCA_OPT = "🔎 Buscar outro alimento (TBCA)…"
REMOVER = "__remover__"  # sentinela usado pelos comandos em texto (zera o item)


def _buscar_tbca_nomes(query, limite=8):
    """Nomes de alimentos da TBCA que contêm os termos buscados (sem pratos)."""
    _curados, indice, _med = _recursos_resolver()
    toks = [t for t in motor.normalizar_texto(query).split() if len(t) > 1]
    if not toks:
        return []
    cands = [r for r in indice
             if not r["eh_prato"] and all(t in r["nome_norm"] for t in toks)]
    cands.sort(key=lambda r: len(r["nome_norm"]))
    return [r["nome"] for r in cands[:limite]]


def _trocar_por_tbca(original_al, tbca_nome):
    """Troca por um alimento da TBCA por EQUIVALÊNCIA CALÓRICA.

    Usar calorias (e não um macro específico) evita gramaturas absurdas quando a
    troca muda de categoria — ex.: arroz (carbo) por patinho (proteína), em que
    bater pelo carboidrato explodiria a quantidade.
    """
    orig_kcal = original_al.get("calorias", 0) or 0
    base = _resolver_alimento(tbca_nome, 100)          # valores por 100 g
    sub_kcal_100 = base.get("calorias", 0) or 0
    if sub_kcal_100 > 0 and orig_kcal > 0:
        gramas = round(100 * orig_kcal / sub_kcal_100, 1)
    else:
        gramas = original_al.get("quantidade_g", 0) or 100
    gramas = max(1.0, min(gramas, 1500.0))             # trava de segurança
    novo = _resolver_alimento(tbca_nome, gramas)
    novo["substituido"] = True
    novo["nome_original"] = original_al.get("nome_principal", "")
    return novo


def _alimento_final(original_al, info):
    """Devolve o alimento conforme a troca registrada (ou o original se não há)."""
    if not info:
        return original_al
    escolha = info.get("escolha", MANTER)
    if not escolha or escolha == MANTER:
        return original_al
    if escolha == REMOVER:
        # Remoção via comando: zera quantidade/macros (sai dos totais).
        removido = dict(original_al)
        removido.update(quantidade_g=0, calorias=0,
                        macros={"carboidratos_g": 0, "proteinas_g": 0, "gorduras_g": 0},
                        removido=True)
        return removido
    if escolha == TBCA_OPT:
        pick = info.get("pick")
        if not pick or pick == "—":
            return original_al
        return _trocar_por_tbca(original_al, pick)
    # Opção curada da nutricionista (ex.: "Mamão - 200g").
    nome, gramas = motor.parse_opcao_substituicao(escolha)
    if not nome or not gramas:
        return original_al
    novo = _resolver_alimento(nome, gramas)
    novo["substituido"] = True
    novo["nome_original"] = original_al.get("nome_principal", "")
    return novo


def _reescalar_para_gramas(al, gramas):
    """Reescala um alimento para uma nova gramatura (macros/calorias proporcionais)."""
    atual = al.get("quantidade_g", 0) or 0
    if atual <= 0 or gramas is None:
        return al
    f = gramas / atual
    m = al.get("macros", {}) or {}
    novo = dict(al)
    novo["quantidade_g"] = round(gramas, 1)
    novo["calorias"] = round((al.get("calorias", 0) or 0) * f, 1)
    novo["macros"] = {k: round(m.get(k, 0) * f, 1)
                      for k in ("carboidratos_g", "proteinas_g", "gorduras_g")}
    novo["ajustado"] = True
    return novo


def _aplicar_substituicoes(orig_slots):
    """Aplica as trocas (em qualquer opção) e recalcula totais.

    As trocas valem para TODAS as opções (chave (slot, opção, alimento)). Os
    totais/validação usam só a opção principal de cada horário (conta_no_total).
    """
    trocas = st.session_state.get("trocas", {})
    adicoes = st.session_state.get("adicoes", {})
    ajustes = st.session_state.get("ajustes", {})
    working = []
    totais = {"kcal": 0.0, "carboidratos_g": 0.0, "proteinas_g": 0.0, "gorduras_g": 0.0}
    for si, grupo in enumerate(orig_slots):
        opcoes = []
        for oi, opcao in enumerate(grupo["opcoes"]):
            finais = []
            for fi, al in enumerate(opcao["alimentos"]):
                novo = _alimento_final(al, trocas.get((si, oi, fi)))
                g_alvo = ajustes.get((si, oi, fi))
                if g_alvo is not None:  # ajuste de quantidade/macro via comando
                    novo = _reescalar_para_gramas(novo, g_alvo)
                finais.append(novo)
            # Alimentos incluídos por comando ("adicionar") entram ao final da opção.
            finais += [dict(a) for a in adicoes.get((si, oi), [])]
            if opcao["conta_no_total"]:
                for novo in finais:
                    totais["kcal"] += novo.get("calorias", 0) or 0
                    for k in ("carboidratos_g", "proteinas_g", "gorduras_g"):
                        totais[k] += novo.get("macros", {}).get(k, 0) or 0
            opcoes.append({**opcao, "alimentos": finais})
        working.append({**grupo, "opcoes": opcoes})
    totais = {k: round(v, 1) for k, v in totais.items()}
    return working, totais


def _tabela_alimentos(alimentos):
    """Tabela limpa do cardápio (mesmo visual para refeição principal e alternativa)."""
    linhas = []
    revisoes = []
    for al in alimentos:
        if al.get("removido"):
            continue  # item removido por comando não aparece no cardápio
        m = al.get("macros", {})
        nome = al.get("nome_principal", "")
        if al.get("substituido"):
            nome = "🔄 " + nome
        elif al.get("adicionado"):
            nome = "➕ " + nome
        elif al.get("ajustado"):
            nome = "📏 " + nome
        linhas.append({
            "Alimento": nome,
            "Porção": motor.descrever_porcao(al),
            "Kcal": round(al.get("calorias", 0)),
            "Carb": m.get("carboidratos_g", 0),
            "Prot": m.get("proteinas_g", 0),
            "Gord": m.get("gorduras_g", 0),
            "Revisão": "automática" if al.get("substituicao_automatica") else "",
        })
        if al.get("substituicao_automatica"):
            revisoes.append(al)
    st.dataframe(linhas, width="stretch", hide_index=True)

    if revisoes:
        with st.expander("⚠️ Revisar substituições automáticas", expanded=True):
            st.warning("Essas trocas foram sugeridas por filtros de aversão/alergia. "
                       "Confira antes de exportar o cardápio.")
            for al in revisoes:
                original = al.get("nome_original", "Alimento original")
                atual = al.get("nome_principal", "")
                score = al.get("score_substituicao")
                score_txt = f" · score {score:.0f}" if isinstance(score, (int, float)) else ""
                st.markdown(f"**{original}** → **{atual}** ({motor.descrever_porcao(al)}{score_txt})")
                motivos = al.get("motivos_substituicao") or []
                alertas = al.get("alertas_substituicao") or []
                if motivos:
                    st.caption("Motivos: " + " · ".join(motivos))
                if alertas:
                    st.caption("Alertas: " + " · ".join(alertas))
                opcoes = al.get("opcoes_substituicao_sugeridas") or []
                alternativas = [
                    f"{o['nome']} ({o['quantidade_g']:.0f} g, score {o['score']:.0f})"
                    for o in opcoes[1:5]
                ]
                if alternativas:
                    st.caption("Alternativas: " + " · ".join(alternativas))


# --- Callbacks que registram a troca escolhida (estado robusto entre reruns) ---

def _cb_troca(si, oi, fi):
    info = st.session_state.trocas.setdefault((si, oi, fi), {})
    info["escolha"] = st.session_state.get(f"sub_{si}_{oi}_{fi}", MANTER)


def _cb_pick(si, oi, fi):
    info = st.session_state.trocas.setdefault((si, oi, fi), {})
    info["pick"] = st.session_state.get(f"subp_{si}_{oi}_{fi}")


def _controle_troca(si, oi, alimentos):
    """Controle recolhido para trocar um alimento — só aparece se a Marcela abrir."""
    with st.expander("🔁 Trocar um alimento (opcional)"):
        idxs = [fi for fi, al in enumerate(alimentos) if (al.get("quantidade_g") or 0) > 0]
        if not idxs:
            st.caption("Nenhum item com quantidade para trocar.")
            return
        nomes = [alimentos[fi]["nome_principal"] for fi in idxs]
        sel = st.selectbox("Qual alimento trocar?", nomes, key=f"subfood_{si}_{oi}")
        fi = idxs[nomes.index(sel)]
        al = alimentos[fi]

        opcoes = [MANTER] + al.get("opcoes_de_substituicao_listadas", []) + [TBCA_OPT]
        info = st.session_state.trocas.get((si, oi, fi), {})
        idx0 = opcoes.index(info["escolha"]) if info.get("escolha") in opcoes else 0
        st.selectbox(f"Trocar “{sel}” por:", opcoes, index=idx0,
                     key=f"sub_{si}_{oi}_{fi}", on_change=_cb_troca, args=(si, oi, fi))

        if st.session_state.get(f"sub_{si}_{oi}_{fi}") == TBCA_OPT:
            q = st.text_input("Buscar na TBCA", key=f"subq_{si}_{oi}_{fi}",
                              placeholder="ex.: maçã, tilápia, batata doce")
            opts = ["—"] + (_buscar_tbca_nomes(q) if q else [])
            pick0 = info.get("pick")
            idxp = opts.index(pick0) if pick0 in opts else 0
            st.selectbox("Escolha o alimento:", opts, index=idxp,
                         key=f"subp_{si}_{oi}_{fi}", on_change=_cb_pick, args=(si, oi, fi))
            st.caption("A gramatura do substituto é calculada para ter as **mesmas "
                       "calorias** do item original.")

        # Resumo das trocas ativas nesta opção + botão para desfazer.
        ativas = []
        for j in idxs:
            inf = st.session_state.trocas.get((si, oi, j), {})
            esc = inf.get("escolha", MANTER)
            if esc and esc != MANTER:
                rotulo = f"TBCA: {inf.get('pick')}" if esc == TBCA_OPT else esc
                ativas.append(f"**{alimentos[j]['nome_principal']}** → {rotulo}")
        if ativas:
            st.caption("Trocas ativas: " + "  ·  ".join(ativas))
            if st.button("Desfazer trocas desta opção", key=f"clr_{si}_{oi}"):
                for j in idxs:
                    st.session_state.trocas.pop((si, oi, j), None)
                st.rerun()


# ---------------------------------------------------------------------------
# Assistente de comandos em texto (trocar / remover / adicionar / ajustar)
# ---------------------------------------------------------------------------

def _principal_oi(grupo):
    """Índice da opção que conta nos totais (a refeição principal do horário)."""
    for oi, op in enumerate(grupo["opcoes"]):
        if op.get("conta_no_total"):
            return oi
    return 0


def _match_indice(texto, nomes):
    """Melhor índice em 'nomes' que casa com 'texto' (por tokens). None se nenhum."""
    alvo = motor.normalizar_texto(texto)
    toks = [t for t in alvo.split() if len(t) > 2]
    melhor, melhor_score = None, 0
    for i, nome in enumerate(nomes):
        nn = motor.normalizar_texto(nome)
        score = sum(1 for t in toks if t in nn)
        if alvo and (alvo in nn or nn in alvo):
            score += 2
        if score > melhor_score:
            melhor, melhor_score = i, score
    return melhor


def _alimentos_principais(grupo):
    """(oi, alimentos) da opção principal de um slot."""
    oi = _principal_oi(grupo)
    return oi, grupo["opcoes"][oi]["alimentos"]


def _achar_alvo_no_slot(alimento_txt, grupo):
    oi, alimentos = _alimentos_principais(grupo)
    fi = _match_indice(alimento_txt, [a.get("nome_principal", "") for a in alimentos])
    return (oi, fi)


# Mapas para o ajuste de macro de uma refeição.
MACRO_CATEGORIA = {"proteina": "Proteína", "carboidrato": "Carboidrato", "gordura": "Gordura"}
MACRO_CHAVE = {"proteina": "proteinas_g", "carboidrato": "carboidratos_g", "gordura": "gorduras_g"}
ROTULO_MACRO = {"proteina": "proteína", "carboidrato": "carboidrato",
                "gordura": "gordura", "calorias": "calorias"}


def _localizar_alvos(alimento_txt, si, slots):
    """Acha o(s) (si, oi, fi) do alimento alvo. Retorna (alvos | None, erro | None)."""
    if si is not None:
        oi, fi = _achar_alvo_no_slot(alimento_txt, slots[si])
        if fi is None:
            return None, f"Não achei “{alimento_txt}” em **{slots[si]['slot']}**."
        return [(si, oi, fi)], None
    alvos = []
    for s, grupo in enumerate(slots):
        o, f = _achar_alvo_no_slot(alimento_txt, grupo)
        if f is not None:
            alvos.append((s, o, f))
    if not alvos:
        return None, f"Não achei “{alimento_txt}” no cardápio."
    if len(alvos) > 1:
        refs = ", ".join(slots[s]["slot"] for s, _o, _f in alvos)
        return None, (f"“{alimento_txt}” aparece em várias refeições ({refs}). "
                      f"Diga em qual aplicar.")
    return alvos, None


def _alvo_valor(atual, modo, valor, unidade):
    """Converte (modo, valor, unidade) num valor absoluto, a partir do atual."""
    u = unidade or "g"
    if u == "x":                                  # multiplicador (ex.: dobrar=2, metade=0.5)
        return max(atual * valor, 0.0)
    if u == "%":
        if modo == "definir":
            return max(atual * valor / 100.0, 0.0)
        delta = atual * valor / 100.0
        return max(atual + delta if modo == "aumentar" else atual - delta, 0.0)
    if modo == "definir":                         # gramas absolutas
        return max(valor, 0.0)
    return max(atual + valor if modo == "aumentar" else atual - valor, 0.0)


def _resolver_ajuste(op, slots, working, si):
    """Resolve um 'ajustar': quantidade de um alimento OU um macro da refeição."""
    macro, modo, valor, unidade = op.get("macro"), op.get("modo"), op.get("valor"), op.get("unidade")
    if modo is None or valor is None:
        return {"tipo": "erro",
                "descricao": "Ajuste sem valor/modo claros — reformule "
                             "(ex.: “aumenta o arroz em 30g”)."}

    # (A) Ajuste de um MACRO da refeição inteira — escala os alimentos da categoria.
    if macro:
        if si is None:
            return {"tipo": "erro",
                    "descricao": f"Ajustar {ROTULO_MACRO[macro]}: diga em qual refeição."}
        oi, alimentos = _alimentos_principais(working[si])
        if macro == "calorias":
            idxs = [fi for fi, a in enumerate(alimentos)
                    if a.get("categoria") != "Outro" and (a.get("quantidade_g") or 0) > 0]
            atual_total = sum(alimentos[fi].get("calorias", 0) or 0 for fi in idxs)
            un = "kcal"
        else:
            cat, chave = MACRO_CATEGORIA[macro], MACRO_CHAVE[macro]
            idxs = [fi for fi, a in enumerate(alimentos)
                    if a.get("categoria") == cat and (a.get("quantidade_g") or 0) > 0]
            atual_total = sum((alimentos[fi].get("macros", {}) or {}).get(chave, 0) for fi in idxs)
            un = "g"
        if not idxs or atual_total <= 0:
            return {"tipo": "erro",
                    "descricao": f"**{slots[si]['slot']}** não tem alimento de "
                                 f"{ROTULO_MACRO[macro]} para escalar — adicione um antes."}
        alvo_total = _alvo_valor(atual_total, modo, valor, unidade)
        f = alvo_total / atual_total
        alvos = {(si, oi, fi): round((alimentos[fi].get("quantidade_g") or 0) * f, 1)
                 for fi in idxs}
        return {"tipo": "ajustar", "alvos": alvos,
                "descricao": f"📈 Ajustar **{ROTULO_MACRO[macro]}** de **{slots[si]['slot']}** "
                             f"de {atual_total:.0f}{un} para {alvo_total:.0f}{un} "
                             f"(escala {len(idxs)} alimento(s) da refeição)."}

    # (B) Ajuste da QUANTIDADE de um alimento específico.
    alvos_loc, erro = _localizar_alvos(op.get("alimento") or "", si, slots)
    if erro:
        return {"tipo": "erro", "descricao": erro}
    s, oi, fi = alvos_loc[0]
    atual = working[s]["opcoes"][oi]["alimentos"][fi].get("quantidade_g", 0) or 0
    nome = working[s]["opcoes"][oi]["alimentos"][fi].get("nome_principal", "")
    if atual <= 0:
        return {"tipo": "erro", "descricao": f"**{nome}** está sem quantidade para ajustar."}
    alvo = _alvo_valor(atual, modo, valor, unidade)
    return {"tipo": "ajustar", "alvos": {(s, oi, fi): round(alvo, 1)},
            "descricao": f"📏 Ajustar **{nome}** em **{slots[s]['slot']}** "
                         f"para {alvo:.0f} g (estava {atual:.0f} g)."}


def _resolver_operacao(op, slots, working):
    """Transforma uma operação da IA num item de plano aplicável + descrição.

    'slots' são os slots originais (para nomes/índices); 'working' é o estado
    atual já com trocas/adições/ajustes (para ler a quantidade vigente).
    """
    acao = op["acao"]
    alimento_txt = op.get("alimento") or ""
    si = _match_indice(op["refeicao"], [g["slot"] for g in slots]) if op.get("refeicao") else None

    if acao == "adicionar":
        if si is None:
            return {"tipo": "erro",
                    "descricao": f"Adicionar “{alimento_txt}”: diga em qual refeição "
                                 f"(ex.: “adiciona {alimento_txt} no lanche da tarde”)."}
        oi = _principal_oi(slots[si])
        gramas = op.get("quantidade_g") or 100.0
        al = _resolver_alimento(alimento_txt, gramas)
        al["adicionado"] = True
        al["nome_principal"] = al.get("nome_principal") or alimento_txt
        return {"tipo": "adicionar", "si": si, "oi": oi, "alimento": al,
                "descricao": f"➕ Adicionar **{al['nome_principal']}** ({gramas:.0f} g) "
                             f"em **{slots[si]['slot']}**."}

    if acao == "ajustar":
        return _resolver_ajuste(op, slots, working, si)

    # trocar / remover: localizar o alimento alvo
    alvos, erro = _localizar_alvos(alimento_txt, si, slots)
    if erro:
        return {"tipo": "erro", "descricao": erro}
    si, oi, fi = alvos[0]
    nome_alvo = slots[si]["opcoes"][oi]["alimentos"][fi].get("nome_principal", alimento_txt)

    if acao == "remover":
        return {"tipo": "remover", "si": si, "oi": oi, "fi": fi,
                "descricao": f"🗑️ Remover **{nome_alvo}** de **{slots[si]['slot']}**."}

    # trocar
    substituto = op.get("substituto") or ""
    if not substituto:
        return {"tipo": "erro",
                "descricao": f"Trocar **{nome_alvo}** por quê? Informe o substituto."}
    nomes = _buscar_tbca_nomes(substituto)
    if not nomes:
        return {"tipo": "erro", "descricao": f"Não encontrei “{substituto}” na base TBCA."}
    pick = nomes[0]
    return {"tipo": "trocar", "si": si, "oi": oi, "fi": fi, "pick": pick,
            "descricao": f"🔄 Trocar **{nome_alvo}** por **{pick}** em "
                         f"**{slots[si]['slot']}** (gramatura ajustada por calorias)."}


def _aplicar_plano(itens):
    """Grava no estado (trocas/adicoes) as operações confirmadas."""
    for item in itens:
        if item["tipo"] == "trocar":
            st.session_state.trocas[(item["si"], item["oi"], item["fi"])] = {
                "escolha": TBCA_OPT, "pick": item["pick"]}
        elif item["tipo"] == "remover":
            st.session_state.trocas[(item["si"], item["oi"], item["fi"])] = {
                "escolha": REMOVER}
        elif item["tipo"] == "adicionar":
            st.session_state.adicoes.setdefault((item["si"], item["oi"]), []).append(
                item["alimento"])
        elif item["tipo"] == "ajustar":
            for chave, gramas in item["alvos"].items():
                st.session_state.ajustes[chave] = gramas


def _contexto_para_ia(slots):
    """Texto compacto das refeições e alimentos atuais (com gramas) para a IA."""
    linhas = []
    for grupo in slots:
        _oi, alimentos = _alimentos_principais(grupo)
        itens = [f"{a.get('nome_principal', '')} ({(a.get('quantidade_g') or 0):.0f}g)"
                 for a in alimentos
                 if not a.get("removido") and (a.get("quantidade_g") or 0) > 0]
        linhas.append(f"- {grupo['slot']}: " + ", ".join(itens))
    return "\n".join(linhas)


def _confirmar_plano():
    plano = st.session_state.get("comando_plano")
    if not plano:
        return
    if plano.get("comentario"):
        st.caption(f"🧠 {plano['comentario']}")
    itens = plano["itens"]
    if not itens:
        st.info("Não entendi nenhuma ação válida nesse comando.")
        st.session_state.comando_plano = None
        return

    aplicaveis = [i for i in itens if i["tipo"] != "erro"]
    for item in itens:
        if item["tipo"] == "erro":
            st.warning("⚠️ " + item["descricao"])
        else:
            st.markdown("• " + item["descricao"])

    c1, c2 = st.columns(2)
    if aplicaveis and c1.button("✅ Aplicar alterações", type="primary",
                                width="stretch"):
        _aplicar_plano(aplicaveis)
        st.session_state.comando_plano = None
        st.rerun()
    if c2.button("✖️ Cancelar", width="stretch"):
        st.session_state.comando_plano = None
        st.rerun()


def _secao_comando(slots, working, api_key, modelo):
    st.subheader("💬 Assistente de comandos")
    st.caption("Digite uma instrução e a IA prepara a alteração para você confirmar. "
               "Ex.: “troca o arroz do almoço por batata doce”, “tira o mamão do "
               "café”, “põe 1 ovo no lanche da tarde”, “aumenta a proteína do jantar "
               "em 20g”, “diminui a aveia pela metade”.")

    cmd = st.text_input("Comando", key="cmd_texto",
                        placeholder="ex.: aumenta a proteína do almoço em 15g")
    if st.button("🤖 Interpretar comando", type="primary"):
        if not cmd.strip():
            st.warning("Digite um comando.")
        else:
            try:
                with st.spinner("Interpretando..."):
                    interpretado = comando_ia.interpretar_comando(
                        cmd, _contexto_para_ia(working), api_key=api_key, modelo=modelo)
                st.session_state.comando_plano = {
                    "itens": [_resolver_operacao(op, slots, working)
                              for op in interpretado["operacoes"]],
                    "comentario": interpretado.get("comentario", ""),
                }
            except comando_ia.ConfiguracaoIAError as e:
                st.error(f"❌ {e}")
            except Exception as e:
                st.error(f"❌ Falha ao interpretar o comando: {e}")

    _confirmar_plano()


def _exibir_cardapio(orig_slots, working_slots):
    st.subheader("🍽️ Cardápio Final")
    for si, (grupo, wgrupo) in enumerate(zip(orig_slots, working_slots)):
        st.markdown(f"#### {grupo['slot']}")
        for oi, (opcao, wopcao) in enumerate(zip(grupo["opcoes"], wgrupo["opcoes"])):
            conta = opcao["conta_no_total"]
            rotulo = opcao["nome_refeicao"] + ("" if conta else "  · _(alternativa)_")
            with st.expander(rotulo, expanded=conta):
                if opcao.get("observacoes"):
                    st.caption(opcao["observacoes"])
                _tabela_alimentos(wopcao["alimentos"])
                _controle_troca(si, oi, opcao["alimentos"])


def _preparo_exportacao(opcao, preparos_curados, preparos_ia):
    nome = opcao.get("nome_refeicao", "")
    if nome in preparos_ia:
        return preparos_ia[nome]
    encontrados = preparos.buscar_preparos(opcao, preparos_curados)
    return encontrados[0] if encontrados else None


def _exportar_markdown(metas, slots, selecionados, incluir_subs=False,
                       incluir_preparos=False, preparos_curados=None, preparos_ia=None):
    """Gera o Markdown do cardápio apenas com as opções selecionadas (já com trocas).

    incluir_subs: quando True, lista sob cada alimento as opções de substituição
    curadas (o lado mais útil do plano para o paciente).
    """
    m = metas
    sel = set(selecionados)
    linhas = [
        "# Cardápio",
        "",
        f"- **Meta calórica:** {m['meta_kcal']} kcal "
        f"(TMB {m['tmb']} · GET {m['get']})",
        f"- **Macros-alvo:** Carb {m['meta_carb_g']:.0f} g · "
        f"Prot {m['meta_prot_g']:.0f} g · Gord {m['meta_gord_g']:.0f} g · "
        f"Fibra {m['meta_fibra_g']:.0f} g",
        "",
    ]
    preparos_curados = preparos_curados or []
    preparos_ia = preparos_ia or {}
    for si, grupo in enumerate(slots):
        for oi, opcao in enumerate(grupo["opcoes"]):
            if (si, oi) not in sel:
                continue
            linhas.append(f"## {opcao['nome_refeicao']}")
            for al in opcao["alimentos"]:
                if al.get("removido"):
                    continue
                linhas.append(f"- {al.get('nome_principal', '')} — {motor.descrever_porcao(al)}")
                if incluir_subs:
                    for sub in al.get("opcoes_de_substituicao_listadas") or []:
                        linhas.append(f"  - ou {sub}")
            if incluir_preparos:
                preparo = _preparo_exportacao(opcao, preparos_curados, preparos_ia)
                if preparo:
                    linhas.append("")
                    linhas.append(preparos.formatar_preparo_markdown(preparo, nivel_titulo="###"))
            linhas.append("")
    return "\n".join(linhas)


def _contexto_clinico_resumido(resultado):
    anamnese = resultado.get("anamnese", {})
    partes = []
    for campo, rotulo in [
        ("patologias", "Patologias"),
        ("alergias", "Alergias"),
        ("intolerancias", "Intolerâncias"),
        ("aversoes", "Aversões"),
    ]:
        vals = anamnese.get(campo) or []
        if vals:
            partes.append(f"{rotulo}: {', '.join(vals)}")
    regras = resultado.get("regras_ativas", [])
    if regras:
        partes.append("Regras ativas: " + ", ".join(r.get("titulo", "") for r in regras))
    return "\n".join(partes) if partes else "Sem restrições clínicas adicionais informadas."


def _opcoes_selecionadas(slots, selecionados):
    for si, grupo in enumerate(slots):
        for oi, opcao in enumerate(grupo["opcoes"]):
            if (si, oi) in selecionados:
                yield si, oi, opcao


def _secao_exportar(resultado, working_slots, totais, api_key, modelo):
    """Seção de exportação: escolha quais opções entram no cardápio do paciente."""
    metas = resultado["metas"]
    st.subheader("📤 Exportar Cardápio")
    st.caption("Marque quais opções de cada refeição vão para o paciente. "
               "Por padrão vem a opção principal de cada horário.")

    todas = st.checkbox("✅ Selecionar TODAS as opções (todas as refeições)")
    selecionados = []
    if todas:
        for si, grupo in enumerate(working_slots):
            for oi in range(len(grupo["opcoes"])):
                selecionados.append((si, oi))
        st.info("Todas as opções serão incluídas no cardápio exportado.")
    else:
        for si, grupo in enumerate(working_slots):
            st.markdown(f"**{grupo['slot']}**")
            for oi, opcao in enumerate(grupo["opcoes"]):
                marcado = st.checkbox(opcao["nome_refeicao"],
                                      value=opcao["conta_no_total"],
                                      key=f"exp_{si}_{oi}")
                if marcado:
                    selecionados.append((si, oi))

    if not selecionados:
        st.warning("Selecione ao menos uma opção para exportar.")
        return

    incluir_subs = st.checkbox(
        "Incluir lista de substituições no cardápio", value=True,
        help="Lista, sob cada alimento, as opções de troca curadas (ex.: as frutas "
             "equivalentes à banana). Desligue para um documento mais enxuto.")

    preparos_curados = _carregar_preparos_curados()
    incluir_preparos = st.checkbox(
        "Incluir modos de preparo curados", value=True,
        help="Inclui receitas/preparos associados a opções como crepioca, toast, açaí e salada.")

    if incluir_preparos:
        sem_preparo = [
            opcao for _si, _oi, opcao in _opcoes_selecionadas(working_slots, selecionados)
            if not _preparo_exportacao(opcao, preparos_curados, st.session_state.preparos_ia)
        ]
        if sem_preparo:
            with st.expander("🤖 Rascunhos de preparo com IA (opcional)"):
                st.caption(
                    f"{len(sem_preparo)} opção(ões) selecionada(s) ainda não têm preparo curado. "
                    "A IA pode gerar rascunhos para revisão, sem alterar macros ou gramaturas."
                )
                if st.button("Gerar rascunhos para opções sem preparo", type="secondary"):
                    if not api_key:
                        st.error("Informe a chave Gemini na barra lateral para gerar rascunhos.")
                    else:
                        limite = 5
                        gerados = 0
                        contexto = _contexto_clinico_resumido(resultado)
                        with st.spinner("Gerando rascunhos de preparo..."):
                            for opcao in sem_preparo[:limite]:
                                nome = opcao.get("nome_refeicao", "")
                                st.session_state.preparos_ia[nome] = preparos.sugerir_preparo_ia(
                                    opcao, api_key=api_key, modelo=modelo,
                                    contexto_clinico=contexto,
                                )
                                gerados += 1
                        st.success(f"{gerados} rascunho(s) gerado(s). Revise no texto exportado.")

    revisao = revisor_cardapio.revisar_cardapio(
        metas,
        working_slots,
        totais,
        resultado.get("anamnese", {}),
        regras_ativas=resultado.get("regras_ativas", []),
        selecionados=selecionados,
        incluir_preparos=incluir_preparos,
        preparos_curados=preparos_curados,
    )
    with st.expander("Checklist antes de baixar", expanded=bool(revisao["alertas"])):
        if not revisao["alertas"]:
            st.success("Sem alertas no checklist de exportação.")
        else:
            for alerta in revisao["alertas"][:15]:
                st.markdown(
                    f"- **{alerta['severidade']} · {alerta['titulo']}**: "
                    f"{alerta['descricao']}"
                )

    md = _exportar_markdown(
        metas,
        working_slots,
        selecionados,
        incluir_subs=incluir_subs,
        incluir_preparos=incluir_preparos,
        preparos_curados=preparos_curados,
        preparos_ia=st.session_state.preparos_ia,
    )
    st.download_button("⬇️ Baixar cardápio (.md)", md,
                       file_name="cardapio.md", mime="text/markdown")
    with st.expander("Ver / copiar texto do cardápio"):
        st.code(md, language="markdown")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    design_marcela.aplicar()
    _init_estado()
    design_marcela.hero()

    # Carrega dados com tratamento de erro.
    try:
        template, banco = _carregar_dados()
    except FileNotFoundError as e:
        st.error(f"❌ {e}")
        st.info(
            "Coloque `cardapio_base.json` em `referencias/cardapio/` e "
            "`alimentos.json` em `referencias/alimentos/`."
        )
        st.stop()
    except Exception as e:
        st.error(f"❌ Erro ao carregar os dados: {e}")
        st.stop()

    api_key, modelo = _sidebar_ia()
    st.sidebar.success(
        f"✅ Template: {template['nome']}\n\n🍎 {len(banco)} alimentos no banco"
    )

    _etapa_anamnese(api_key, modelo)
    params = _etapa_revisao()
    if params:
        _gerar(template, banco, params)

    resultado = st.session_state.resultado
    if resultado:
        # Aplica as trocas escolhidas pela Marcela e recalcula tudo na hora.
        working_slots, totais = _aplicar_substituicoes(resultado["slots"])

        st.divider()
        _exibir_resumo(resultado["metas"])
        st.divider()
        _exibir_validacao(resultado["metas"], working_slots, totais)
        st.divider()
        _exibir_revisao_clinica(resultado, working_slots, totais)
        for aviso in resultado.get("avisos", []):
            st.warning(f"⚠️ {aviso}")
        st.divider()
        _secao_comando(resultado["slots"], working_slots, api_key, modelo)
        st.divider()
        _exibir_cardapio(resultado["slots"], working_slots)

        st.divider()
        _secao_exportar(resultado, working_slots, totais, api_key, modelo)


if __name__ == "__main__":
    main()
