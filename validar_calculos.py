# -*- coding: utf-8 -*-
"""
validar_calculos.py — Confere objetivamente os números do app
==============================================================

Roda 3 verificações independentes para você (e a nutricionista) confiar nos
cálculos:

  1. FÓRMULAS METABÓLICAS: recalcula TMB/GET/macros à mão, inclusive com meta
     calórica manual, e compara com o que o motor produz (devem bater exatamente).
  2. ATWATER (coerência de cada alimento): para todo alimento, as calorias devem
     ser ~ 4×carbo + 4×proteína + 9×gordura. Se um alimento fugir muito disso,
     o dado nutricional dele é suspeito (digitação/match errado).
  3. SOMA DAS REFEIÇÕES: o total de cada refeição = soma dos alimentos (sem erro
     de arredondamento grosseiro).

Uso:  python validar_calculos.py
"""

import cardapio_io
import motor
import preparos
import regras_clinicas
import revisor_cardapio

TOL_ATWATER_PCT = 25     # % de desvio tolerado entre kcal informada e Atwater
TOL_ATWATER_ABS = 20     # kcal de desvio absoluto mínimo para reclamar


def validar_formulas():
    print("=" * 70)
    print("1) FÓRMULAS METABÓLICAS E META MANUAL (homem, 92kg, 178cm, 34a)")
    print("=" * 70)
    m = motor.calcular_metas(92, 178, 34, "Masculino", 1.55, "Emagrecimento")

    # Conta à mão (confira numa calculadora):
    tmb = 88.362 + 13.397*92 + 4.799*178 - 5.677*34  # Harris-Benedict 1984
    get = tmb * 1.55
    meta = get - 400
    prot = 2.0 * 92                               # 2 g/kg (emagrecimento)
    gord = 0.25 * meta / 9                         # 25% das kcal / 9
    carb = (meta - prot*4 - gord*9) / 4            # restante / 4

    linhas = [
        ("TMB", tmb, m["tmb"]),
        ("GET", get, m["get"]),
        ("Meta kcal", meta, m["meta_kcal"]),
        ("Proteína (g)", prot, m["meta_prot_g"]),
        ("Gordura (g)", gord, m["meta_gord_g"]),
        ("Carboidrato (g)", carb, m["meta_carb_g"]),
    ]
    ok = True
    for nome, manual, motor_val in linhas:
        bate = abs(round(manual, 1) - motor_val) <= 1
        ok = ok and bate
        print(f"  {nome:18} à mão={manual:8.1f}  motor={motor_val:8.1f}  "
              f"{'OK' if bate else 'DIVERGE!'}")

    meta_manual = 2100
    prot2 = 1.8 * 92
    gord2 = 0.30 * meta_manual / 9
    carb2 = (meta_manual - prot2*4 - gord2*9) / 4
    m2 = motor.calcular_metas(
        92, 178, 34, "Masculino", 1.55, "Emagrecimento",
        meta_kcal_manual=meta_manual,
        meta_prot_g_manual=prot2,
        meta_carb_g_manual=carb2,
        meta_gord_g_manual=gord2,
    )
    ajuste2 = meta_manual - get
    linhas_manuais = [
        ("Meta manual", meta_manual, m2["meta_kcal"]),
        ("Ajuste vs GET", ajuste2, m2["ajuste_kcal"]),
        ("Proteína manual", prot2, m2["meta_prot_g"]),
        ("Gordura manual", gord2, m2["meta_gord_g"]),
        ("Carbo manual", carb2, m2["meta_carb_g"]),
    ]
    print("  -- Meta calórica definida pela nutricionista --")
    for nome, manual, motor_val in linhas_manuais:
        bate = abs(round(manual, 1) - motor_val) <= 1
        ok = ok and bate
        print(f"  {nome:18} à mão={manual:8.1f}  motor={motor_val:8.1f}  "
              f"{'OK' if bate else 'DIVERGE!'}")

    base = (148.6, 228.7, 42.0)
    por_kcal = motor.readequar_metas_macros(
        2012, *base, ancora="meta_kcal"
    )
    por_proteina = motor.readequar_metas_macros(
        2012,
        160.0,
        por_kcal["meta_carb_g"],
        por_kcal["meta_gord_g"],
        ancora="meta_prot_g",
    )
    por_carbo = motor.readequar_metas_macros(
        2012,
        por_proteina["meta_prot_g"],
        250.0,
        por_proteina["meta_gord_g"],
        ancora="meta_carb_g",
    )
    por_gordura = motor.readequar_metas_macros(
        2012,
        por_carbo["meta_prot_g"],
        por_carbo["meta_carb_g"],
        50.0,
        ancora="meta_gord_g",
    )
    readequacoes = (por_kcal, por_proteina, por_carbo, por_gordura)
    ok_tetos = all(
        0 <= 2012 - resultado["kcal_macros"] < 1
        for resultado in readequacoes
    )
    ok_vinculos = (
        all(por_kcal[chave] != valor for chave, valor in zip(
            ("meta_prot_g", "meta_carb_g", "meta_gord_g"), base
        ))
        and por_proteina["meta_prot_g"] == 160.0
        and por_proteina["meta_carb_g"] != por_kcal["meta_carb_g"]
        and por_proteina["meta_gord_g"] != por_kcal["meta_gord_g"]
        and por_carbo["meta_prot_g"] != por_proteina["meta_prot_g"]
        and por_carbo["meta_gord_g"] != por_proteina["meta_gord_g"]
        and por_gordura["meta_prot_g"] != por_carbo["meta_prot_g"]
        and por_gordura["meta_carb_g"] != por_carbo["meta_carb_g"]
    )
    limitado = motor.readequar_metas_macros(
        1500, 500, 200, 50, ancora="meta_prot_g"
    )
    ok_limite = (
        limitado["limitado"]
        and limitado["meta_prot_g"] == 375.0
        and limitado["kcal_macros"] == 1500.0
    )
    ok = ok and ok_tetos and ok_vinculos and ok_limite
    print(
        "  Readequação dos quatro campos: "
        f"{'OK' if ok_tetos and ok_vinculos else 'DIVERGE!'}"
    )
    print(f"  Limite de macro impossível: {'OK' if ok_limite else 'DIVERGE!'}")
    print(f"  => Fórmulas {'CONFEREM' if ok else 'COM PROBLEMA'}\n")
    return ok


def validar_atwater():
    print("=" * 70)
    print("2) COERÊNCIA DE CADA ALIMENTO (Atwater: kcal ≈ 4C + 4P + 9G)")
    print("=" * 70)
    tpl = motor.carregar_template()
    suspeitos = []
    total = 0
    for ref in tpl["refeicoes"]:
        for a in ref["alimentos"]:
            kcal = a.get("calorias", 0) or 0
            if kcal <= 0:
                continue
            total += 1
            mm = a.get("macros", {})
            atw = 4*mm.get("carboidratos_g", 0) + 4*mm.get("proteinas_g", 0) + 9*mm.get("gorduras_g", 0)
            desvio = abs(kcal - atw)
            pct = (desvio / kcal * 100) if kcal else 0
            if desvio > TOL_ATWATER_ABS and pct > TOL_ATWATER_PCT:
                suspeitos.append((a["nome_principal"], kcal, round(atw, 1), round(pct)))

    if not suspeitos:
        print(f"  Todos os {total} alimentos com calorias coerentes (Atwater). OK\n")
    else:
        print(f"  {len(suspeitos)} de {total} alimentos com possível inconsistência:")
        for nome, kcal, atw, pct in sorted(suspeitos, key=lambda x: -x[3]):
            print(f"    - {nome[:40]:40} informado={kcal:6.0f}kcal  Atwater={atw:6.0f}  desvio {pct}%")
        print("  (Confira esses no rótulo/TBCA — podem ser fibra, álcool ou match errado.)\n")
    return suspeitos


def validar_somas():
    print("=" * 70)
    print("3) SOMA DAS REFEIÇÕES = soma dos alimentos")
    print("=" * 70)
    tpl = motor.carregar_template()
    banco = motor.carregar_banco_alimentos()
    metas = motor.calcular_metas(92, 178, 34, "Masculino", 1.55, "Emagrecimento")
    slots, totais, _, _ = motor.gerar_cardapio(tpl, banco, metas, [])

    soma = {"kcal": 0.0, "carboidratos_g": 0.0, "proteinas_g": 0.0, "gorduras_g": 0.0}
    for s in slots:
        for op in s["opcoes"]:
            if not op["conta_no_total"]:
                continue
            for a in op["alimentos"]:
                soma["kcal"] += a.get("calorias", 0) or 0
                for k in ("carboidratos_g", "proteinas_g", "gorduras_g"):
                    soma[k] += a.get("macros", {}).get(k, 0) or 0

    ok = True
    for k in soma:
        bate = abs(round(soma[k], 1) - totais[k]) <= 1
        ok = ok and bate
        print(f"  {k:16} recalculado={soma[k]:8.1f}  motor={totais[k]:8.1f}  "
              f"{'OK' if bate else 'DIVERGE!'}")
    print(f"  => Somas {'CONFEREM' if ok else 'COM PROBLEMA'}\n")
    return ok

def validar_base_marcela():
    print("=" * 70)
    print("4) CARDÁPIO DA MARCELA COMO BASE PRINCIPAL")
    print("=" * 70)
    tpl = motor.carregar_template()
    banco = motor.carregar_banco_alimentos()
    metas = motor.calcular_metas(
        70, 170, 30, "Feminino", 1.55, "Manutenção",
        meta_kcal_manual=1800,
        meta_prot_g_manual=100,
        meta_carb_g_manual=220,
        meta_gord_g_manual=55,
    )
    slots, _, _, _ = motor.gerar_cardapio(tpl, banco, metas, [])

    assinatura_template = [
        (
            slot,
            refeicao.get("nome_refeicao"),
            tuple(
                alimento.get("nome_principal")
                for alimento in refeicao.get("alimentos", [])
            ),
        )
        for slot, refeicoes in motor.agrupar_em_slots(tpl["refeicoes"])
        for refeicao in refeicoes
    ]
    assinatura_gerada = [
        (
            grupo["slot"],
            opcao.get("nome_refeicao"),
            tuple(
                alimento.get("nome_principal")
                for alimento in opcao.get("alimentos", [])
            ),
        )
        for grupo in slots
        for opcao in grupo["opcoes"]
    ]
    sem_trocas = not any(
        alimento.get("substituicao_automatica")
        for grupo in slots
        for opcao in grupo["opcoes"]
        for alimento in opcao["alimentos"]
    )
    ok = assinatura_template == assinatura_gerada and sem_trocas
    print(f"  Estrutura e alimentos da Marcela preservados: {'OK' if ok else 'DIVERGE!'}")
    print("  TBCA fica reservada a trocas/adições explicitamente solicitadas.\n")
    return ok




def validar_limites_edicao_pacote():
    print("=" * 70)
    print("5) LIMITES RÍGIDOS, EDIÇÃO REATIVA E PACOTE EDITÁVEL")
    print("=" * 70)
    tpl = motor.carregar_template()
    banco = motor.carregar_banco_alimentos()
    cenarios = [
        (1500, 15, 200, 50),
        (2100, 165.6, 201.9, 70),
    ]
    ok = True
    ultimo = None
    for kcal, prot, carb, gord in cenarios:
        metas = motor.calcular_metas(
            70, 170, 30, "Feminino", 1.55, "Manutenção",
            meta_kcal_manual=kcal,
            meta_prot_g_manual=prot,
            meta_carb_g_manual=carb,
            meta_gord_g_manual=gord,
        )
        slots, totais, _, avisos = motor.gerar_cardapio(
            tpl, banco, metas, []
        )
        validacao = motor.validar_resultado(slots, totais, metas)
        passou = validacao["limites_ok"]
        ok = ok and passou
        print(
            f"  {kcal} kcal / P {prot:g} g: "
            f"{totais} · {'OK' if passou else 'EXCEDEU!'}"
        )
        if avisos:
            print("    observação:", avisos[0])
        ultimo = (metas, slots, totais)

    metas, slots, totais = ultimo
    alimento = next(
        alimento
        for grupo in slots
        for opcao in grupo["opcoes"]
        if opcao["conta_no_total"]
        for alimento in opcao["alimentos"]
        if (alimento.get("quantidade_g") or 0) >= 10
        and (alimento.get("macros", {}).get("proteinas_g") or 0) > 0
    )
    quantidade_inicial = alimento["quantidade_g"]
    proteina_inicial = alimento["macros"]["proteinas_g"]
    ajustado = motor.reescalar_alimento(
        alimento, quantidade_inicial + 5
    )
    esperado = proteina_inicial * (
        ajustado["quantidade_g"] / quantidade_inicial
    )
    ok_reativo = abs(
        ajustado["macros"]["proteinas_g"] - esperado
    ) <= 0.01
    inteiro = motor.quantidade_paciente(ajustado)
    ok_inteiro = isinstance(inteiro, int) and inteiro <= ajustado["quantidade_g"]

    ok_multiplos_5 = (
        motor.arredondar_multiplo_proximo(55.3) == 55
        and motor.arredondar_multiplo_proximo(57.5) == 60
    )
    for grupo in slots:
        principal = next(
            opcao for opcao in grupo["opcoes"]
            if opcao["conta_no_total"]
        )
        limites_refeicao = motor.totais_da_opcao(principal, casas=6)
        for opcao in grupo["opcoes"]:
            alimentos_paciente = motor.arredondar_alimentos_paciente(
                opcao["alimentos"], limites_refeicao
            )
            ok_multiplos_5 = ok_multiplos_5 and all(
                (
                    float(alimento.get("quantidade_g", 0) or 0)
                    % motor.PASSO_PORCAO_PACIENTE
                ) == 0
                for alimento in alimentos_paciente
            )
            totais_paciente = motor.somar_alimentos(
                alimentos_paciente, casas=6
            )
            ok_multiplos_5 = ok_multiplos_5 and all(
                totais_paciente[chave] <= limites_refeicao[chave] + 1e-6
                for chave in motor.CHAVES_NUTRICIONAIS
            )

    resultado = {
        "metas": metas,
        "anamnese": {"idade": 30},
        "parametros": {"idade": 30},
        "excluidos": [],
        "regras_ativas": [],
        "avisos": [],
    }
    texto = cardapio_io.serializar_pacote(resultado, slots, totais)
    restaurado = cardapio_io.carregar_pacote(texto)
    ok_pacote = (
        restaurado["metas"] == metas
        and restaurado["slots"] == slots
    )
    ok = ok and ok_reativo and ok_inteiro and ok_multiplos_5 and ok_pacote
    print(f"  Recalculo proporcional ao editar: {'OK' if ok_reativo else 'DIVERGE!'}")
    print(f"  Quantidade inteira segura: {'OK' if ok_inteiro else 'DIVERGE!'}")
    print(f"  Exportação em múltiplos de 5 sem exceder: {'OK' if ok_multiplos_5 else 'DIVERGE!'}")
    print(f"  Exportar/importar JSON editável: {'OK' if ok_pacote else 'DIVERGE!'}\n")
    return ok

def _assinatura_substituicoes(slots):
    assinatura = []
    for grupo in slots:
        for op in grupo["opcoes"]:
            for al in op["alimentos"]:
                if not al.get("substituicao_automatica"):
                    continue
                assinatura.append((
                    grupo["slot"],
                    al.get("nome_original"),
                    al.get("nome_principal"),
                    al.get("quantidade_g"),
                    tuple(
                        (o["nome"], o["quantidade_g"], o["score"])
                        for o in al.get("opcoes_substituicao_sugeridas", [])
                    ),
                ))
    return assinatura


def validar_substituicoes_deterministicas():
    print("=" * 70)
    print("6) SUBSTITUIÇÕES AUTOMÁTICAS DETERMINÍSTICAS")
    print("=" * 70)
    tpl = motor.carregar_template()
    banco = motor.carregar_banco_alimentos()
    metas = motor.calcular_metas(92, 178, 34, "Masculino", 1.55, "Emagrecimento")

    slots1, _, _, _ = motor.gerar_cardapio(tpl, banco, metas, ["banana"])
    slots2, _, _, _ = motor.gerar_cardapio(tpl, banco, metas, ["banana"])
    sig1 = _assinatura_substituicoes(slots1)
    sig2 = _assinatura_substituicoes(slots2)

    ok = bool(sig1) and sig1 == sig2
    print(f"  Substituições encontradas: {len(sig1)}")
    print(f"  Repetição com mesma entrada: {'OK' if ok else 'DIVERGE!'}")
    if sig1:
        slot, original, escolhido, gramas, opcoes = sig1[0]
        print(f"  Exemplo: {slot} | {original} -> {escolhido} ({gramas:.0f}g)")
        print(f"  Opções ranqueadas no exemplo: {len(opcoes)}")
    print()
    return ok


def validar_regras_preparos_revisor():
    print("=" * 70)
    print("7) REGRAS CLÍNICAS, PREPAROS E CHECKLIST")
    print("=" * 70)
    anamnese = {
        "patologias": ["Diabetes"],
        "intolerancias": ["lactose"],
        "alergias": [],
        "aversoes": [],
        "medicamentos": [],
        "exames_observacoes": "glicemia alterada",
    }
    regras = regras_clinicas.avaliar_anamnese(anamnese)
    termos = regras_clinicas.termos_exclusao(anamnese, regras)
    ok_regras = any(r["id"] == "diabetes" for r in regras) and "leite" in [t.lower() for t in termos]

    tpl = motor.carregar_template()
    banco = motor.carregar_banco_alimentos()
    metas = motor.calcular_metas(92, 178, 34, "Masculino", 1.55, "Emagrecimento")
    slots, totais, _, _ = motor.gerar_cardapio(tpl, banco, metas, termos)

    prep = None
    for refeicao in tpl["refeicoes"]:
        if "Crepioca" in refeicao.get("nome_refeicao", ""):
            prep = preparos.buscar_preparos(refeicao)
            break
    ok_preparo = bool(prep)

    revisao = revisor_cardapio.revisar_cardapio(metas, slots, totais, anamnese, regras)
    ok_revisor = "alertas" in revisao and isinstance(revisao["alertas"], list)

    print(f"  Regras detectadas: {len(regras)} {'OK' if ok_regras else 'DIVERGE!'}")
    print(f"  Termos de exclusão: {', '.join(termos) if termos else '-'}")
    print(f"  Preparo curado para Crepioca: {'OK' if ok_preparo else 'DIVERGE!'}")
    print(f"  Checklist gerado: {len(revisao['alertas'])} alerta(s) {'OK' if ok_revisor else 'DIVERGE!'}\n")
    return ok_regras and ok_preparo and ok_revisor


def validar_reativacao_confirmacao_e_texto_livre():
    print("=" * 70)
    print("8) REATIVAÇÃO DE 0 G, READEQUAÇÃO, CONFIRMAÇÃO E TEXTO LIVRE")
    print("=" * 70)
    template = motor.carregar_template()
    banco = motor.carregar_banco_alimentos()
    metas = motor.calcular_metas(
        70, 165, 35, "Feminino", 1.725, "Emagrecimento",
        meta_kcal_manual=2012,
        meta_prot_g_manual=148.6,
        meta_carb_g_manual=228.7,
        meta_gord_g_manual=42.0,
    )
    slots, _, _, _ = motor.gerar_cardapio(template, banco, metas, [])
    pre_treino = next(
        grupo for grupo in slots
        if "pre treino" in motor.normalizar_texto(grupo["slot"])
    )
    principal = next(
        opcao for opcao in pre_treino["opcoes"]
        if opcao.get("conta_no_total")
    )
    opcao = pre_treino["opcoes"][1]
    indice_geleia = next(
        indice for indice, alimento in enumerate(opcao["alimentos"])
        if "geleia" in motor.normalizar_texto(
            alimento.get("nome_principal", "")
        )
    )
    geleia = opcao["alimentos"][indice_geleia]
    ok_referencia = (
        geleia.get("quantidade_g") == 0
        and bool(geleia.get("referencia_nutricional"))
    )
    limites = motor.totais_da_opcao(principal, casas=6)
    readequados, diagnostico = motor.readequar_opcao_com_ancora(
        opcao["alimentos"], limites, indice_geleia, 25
    )
    totais_readequados = motor.somar_alimentos(readequados, casas=6)
    ok_readequacao = (
        readequados[indice_geleia]["quantidade_g"] == 25
        and not diagnostico["limitado"]
        and all(
            totais_readequados[chave] <= limites[chave] + 1e-6
            for chave in motor.CHAVES_NUTRICIONAIS
        )
    )

    livres = [
        alimento
        for refeicao in template["refeicoes"]
        for alimento in refeicao.get("alimentos", [])
        if motor.eh_salada_ou_legume(alimento)
    ]
    ok_texto_livre = bool(livres) and all(
        alimento.get("orientacao_paciente")
        for alimento in livres
    )

    alimento_excedido = {
        "nome_principal": "Teste",
        "quantidade_g": 100.0,
        "calorias": 120.0,
        "macros": {
            "carboidratos_g": 25.0,
            "proteinas_g": 12.0,
            "gorduras_g": 6.0,
        },
    }
    limites_teste = {
        "kcal": 100.0,
        "carboidratos_g": 20.0,
        "proteinas_g": 10.0,
        "gorduras_g": 5.0,
    }
    slots_teste = [{
        "slot": "Teste",
        "opcoes": [{
            "nome_refeicao": "Teste - Opção 1",
            "conta_no_total": True,
            "limites_nutricionais": limites_teste,
            "alimentos": [alimento_excedido],
        }],
    }]
    metas_teste = {
        "meta_kcal": 100.0,
        "meta_carb_g": 20.0,
        "meta_prot_g": 10.0,
        "meta_gord_g": 5.0,
    }
    totais_teste = motor.somar_totais(slots_teste)
    validacao = motor.validar_resultado(
        slots_teste, totais_teste, metas_teste
    )
    ok_detalhes = (
        not validacao["limites_ok"]
        and validacao["excedentes"]["kcal"]["excesso"] == 20.0
        and validacao["opcoes_excedentes"][0]["detalhes"]["kcal"]["limite"]
        == 100.0
    )

    print(f"  Referência preservada em alimento 0 g: {'OK' if ok_referencia else 'DIVERGE!'}")
    print(f"  Geleia reativada com readequação da opção: {'OK' if ok_readequacao else 'DIVERGE!'}")
    print(f"  Saladas/legumes com orientação textual: {'OK' if ok_texto_livre else 'DIVERGE!'}")
    print(f"  Valores excedidos detalhados para confirmação: {'OK' if ok_detalhes else 'DIVERGE!'}\n")
    return ok_referencia and ok_readequacao and ok_texto_livre and ok_detalhes


if __name__ == "__main__":
    f = validar_formulas()
    s = validar_atwater()
    z = validar_somas()
    b = validar_base_marcela()
    l = validar_limites_edicao_pacote()
    d = validar_substituicoes_deterministicas()
    r = validar_regras_preparos_revisor()
    n = validar_reativacao_confirmacao_e_texto_livre()
    print("=" * 70)
    print("RESUMO:",
          "Fórmulas", "OK" if f else "X",
          "| Atwater", f"{len(s)} suspeitos",
          "| Somas", "OK" if z else "X",
          "| Base Marcela", "OK" if b else "X",
          "| Limites/Edição/Importação", "OK" if l else "X",
          "| Substituições", "OK" if d else "X",
          "| Regras/Preparo/Revisor", "OK" if r else "X",
          "| Reativação/Confirmação/Texto", "OK" if n else "X")
    print("=" * 70)
