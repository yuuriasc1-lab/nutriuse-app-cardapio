# App Cardapio Marcela

MVP em Streamlit para apoiar a geracao de cardapios a partir de anamnese,
metas clinicas e base nutricional.

A meta calorica final e definida pela Marcela antes da geracao do cardapio.
TMB e GET aparecem como referencia; os sliders de meta kcal, proteina e gordura
recalculam os macros em tempo real antes de enviar os dados ao motor.

## Como rodar

```powershell
pip install -r requirements.txt
streamlit run app.py
```

Para usar a leitura por IA, informe a chave Gemini na barra lateral do app ou
configure `GEMINI_API_KEY` em `.streamlit/secrets.toml`.

## Organizacao das referencias

```text
docs/
  Documentação.md
  DOCUMENTO PARA CRIAÇÃO DO CARDÁPIO.md

referencias/
  cardapio/
    Plano_alimentar_base.txt
    cardapio_base.json
    cardapio_base.json.bak
  alimentos/
    alimentos.json
    alimentos.txt
    macros_curados.json
    medidas_caseiras.json
  preparos/
    preparos_curados.json
  prompts/
    anamnese.md
    comando_cardapio.md
    preparo.md
    revisao_clinica.md
  regras/
    regras_clinicas.json
  tabelas_complementares/
    TACO_...
    TBCA_...
    Resposta_Glicemica...
  relatorios/
    relatorio_conversao.txt

logs/
  streamlit_log.txt
```

## Arquivos principais

- `app.py`: interface Streamlit e fluxo de revisao/exportacao.
- `motor.py`: calculos, metas manuais, geracao do cardapio e substituicoes automaticas.
- `anamnese_ia.py`: extracao de anamnese por Gemini.
- `comando_ia.py`: interpretacao de comandos em linguagem natural.
- `ia_servico.py`: cliente central de IA para respostas JSON.
- `regras_clinicas.py`: aplica regras deterministicas de doencas/restricoes.
- `preparos.py`: associa modos de preparo curados e gera rascunhos por IA.
- `revisor_cardapio.py`: checklist antes da exportacao.
- `converter_cardapio.py`: converte `referencias/cardapio/Plano_alimentar_base.txt`
  em `referencias/cardapio/cardapio_base.json`.
- `validar_calculos.py`: valida formulas, somas, Atwater e determinismo das
  substituicoes.

## Camadas de IA e revisao

- A IA le a anamnese e interpreta comandos, mas nao calcula macros.
- A geracao usa a meta calorica final aprovada na tela de revisao; GET e ajuste
  sao informativos para apoiar a decisao clinica.
- Regras clinicas ficam em `referencias/regras/regras_clinicas.json` e podem
  gerar alertas ou adicionar termos aos filtros alimentares.
- Modos de preparo curados ficam em `referencias/preparos/preparos_curados.json`.
- Rascunhos de preparo por IA sao opcionais e aparecem marcados como rascunho
  para revisao.
- Antes do download, o app mostra um checklist com alertas clinicos, substituicoes
  automaticas pendentes, desvios de meta e preparos ausentes.

## Fluxo para atualizar o cardapio base

1. Edite `referencias/cardapio/Plano_alimentar_base.txt`.
2. Se necessario, ajuste alimentos de rotulo em
   `referencias/alimentos/macros_curados.json`.
3. Rode:

```powershell
python -X utf8 -B converter_cardapio.py
```

O conversor atualiza `referencias/cardapio/cardapio_base.json`, cria backup do
JSON anterior e grava a auditoria em `referencias/relatorios/relatorio_conversao.txt`.

## Validacao

```powershell
python -X utf8 -B validar_calculos.py
```

Use `-X utf8` no Windows para evitar erro de codificacao ao imprimir simbolos no
terminal.
