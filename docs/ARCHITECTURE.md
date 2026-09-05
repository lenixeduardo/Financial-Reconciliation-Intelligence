# Architecture — Financial Reconciliation Intelligence v0.3

## Ingestion

Lê CSV/XLSX e preserva cada linha original para auditoria.

## Schema Mapping

Sugere colunas por aliases simples; a confirmação continua humana.

## Reconciliation Templates

Templates persistem uma configuração reutilizável de conciliação no SQLite do MVP:

```text
template_id
name / description
left_mapping
right_mapping
rules
left_columns / right_columns
created_at / updated_at
```

Antes da aplicação, a API compara as colunas referenciadas pelos mappings com os schemas das duas bases carregadas. O endpoint `/templates/{id}/apply` retorna `compatible=false` e as colunas ausentes quando o schema mudou.

O `template_id` usado em uma execução também é persistido no payload da conciliação para manter rastreabilidade do processo configurado.

## Matching Engine

O motor é determinístico e executa quatro estágios de matching:

1. `1:1` exato com alta confiança.
2. `1:N` — uma linha da base A contra uma combinação de linhas da base B.
3. `N:1` — uma combinação de linhas da base A contra uma linha da base B.
4. `1:1` aproximado/divergente para os itens restantes.

### Group candidate generation

Para evitar busca irrestrita:

- filtra sinais incompatíveis de valor;
- filtra datas fora da tolerância quando datas estão mapeadas;
- descarta valores individuais maiores que o alvo no mesmo sinal;
- limita candidatos por `group_candidate_limit`;
- limita a combinação por `max_group_size`.

As combinações são validadas por soma exata dentro da tolerância e depois recebem score por data, descrição e documento.

## Cardinalidades

- `1:1`: uma linha em cada lado.
- `1:N`: uma linha da base principal conciliada com várias linhas da base comparada.
- `N:1`: várias linhas da base principal conciliadas com uma linha da base comparada.

Cada `MatchPair` preserva os campos legados de 1:1 e adiciona:

```text
left_indices[]
right_indices[]
left_rows[]
right_rows[]
match_cardinality
```

## Proteção contra double matching

O engine mantém conjuntos de índices disponíveis. Quando um match 1:1 ou agrupado é aceito como candidato, todos os índices participantes são removidos antes da próxima escolha. Assim, a mesma linha nunca aparece em dois grupos.

## Classificações

- `MATCH`: composição dentro da tolerância e confiança acima do limiar automático.
- `PROBABLE_MATCH`: composição plausível que exige revisão.
- `DIVERGENCE`: correspondência forte 1:1 com diferença financeira.
- `UNMATCHED`: nenhum candidato acima do limiar mínimo.
- `DUPLICATE`: identificador documental + valor repetidos dentro da mesma base.
- `APPROVED` / `REJECTED`: decisão manual.

## Match rate

A taxa de match usa **linhas da base principal efetivamente conciliadas**, e não apenas quantidade de grupos. Portanto, um `N:1` que concilie três linhas aumenta a cobertura em três registros.

## Princípio de segurança

O LLM não participa da soma, seleção de combinações ou decisão financeira. Uma futura camada de IA poderá explicar exceções e sugerir regras, mas o resultado de conciliação continuará sendo calculado pelo engine determinístico.
