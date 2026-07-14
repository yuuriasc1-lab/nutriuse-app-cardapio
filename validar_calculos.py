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
    tmb = 10*92 + 6.25*178 - 5*34 + 5            # Mifflin-St Jeor (homem)
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
    m2 = motor.calcular_metas(
        92, 178, 34, "Masculino", 1.55, "Emagrecimento",
        prot_g_kg=1.8, perc_gordura=0.30, meta_kcal_manual=meta_manual,
    )
    prot2 = 1.8 * 92
    gord2 = 0.30 * meta_manual / 9
    carb2 = (meta_manual - prot2*4 - gord2*9) / 4
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
    print("4) SUBSTITUIÇÕES AUTOMÁTICAS DETERMINÍSTICAS")
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
    print("5) REGRAS CLÍNICAS, PREPAROS E CHECKLIST")
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


if __name__ == "__main__":
    f = validar_formulas()
    s = validar_atwater()
    z = validar_somas()
    d = validar_substituicoes_deterministicas()
    r = validar_regras_preparos_revisor()
    print("=" * 70)
    print("RESUMO:",
          "Fórmulas", "OK" if f else "X",
          "| Atwater", f"{len(s)} suspeitos",
          "| Somas", "OK" if z else "X",
          "| Substituições", "OK" if d else "X",
          "| Regras/Preparo/Revisor", "OK" if r else "X")
    print("=" * 70)
