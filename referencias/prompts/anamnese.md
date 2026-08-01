Prompt base da leitura de anamnese.

A implementacao atual ainda monta o schema em `anamnese_ia.py`, mas este arquivo
documenta o comportamento esperado: extrair apenas dados presentes no texto,
inferindo somente o fator de atividade quando a descricao permitir, e retornar
JSON estruturado para revisao humana.
