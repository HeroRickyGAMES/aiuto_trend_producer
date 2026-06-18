"""
script_writer.py
Gera roteiro completo usando Ollama local.
Retorna estrutura com intro, blocos de cenas e outro.
"""

import requests
import json
import logging
import re
from dataclasses import dataclass, field
from typing import List

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="[ScriptWriter] %(message)s")


@dataclass
class Cena:
    numero: int
    titulo: str
    naracao: str                      # texto para TTS
    palavras_chave_midia: List[str]   # busca no Pexels


@dataclass
class Roteiro:
    titulo_video: str
    descricao_youtube: str
    tags: List[str]
    thumb_texto: str                  # texto curto para thumbnail
    cenas: List[Cena] = field(default_factory=list)
    roteiro_completo: str = ""        # naracao completa para TTS


class ScriptWriter:
    def __init__(self, config: dict):
        self.config = config
        self.ollama_cfg = config.get("llm", {})
        self.roteiro_cfg = config.get("roteiro", {})
        self.script_cfg = config.get("script", {})
        self.channel_cfg = config.get("channel", {})
        self.base_url = self.ollama_cfg.get("base_url", "http://localhost:11434")
        self.model = self.ollama_cfg.get("model", "llama3")
        self.temperature = self.ollama_cfg.get("temperature", 0.8)
        # Duração: main.py injeta em roteiro.duracao_alvo_minutos; senão script.duration_target; senão 5 min
        self.duracao_min = (
            self.roteiro_cfg.get("duracao_alvo_minutos")
            or (self.script_cfg.get("duration_target", 0) / 60.0)
            or 5
        )
        # Nome do canal: prefere name_tts (grafia fonética p/ o TTS ler certo), senão name
        self.canal = (
            self.channel_cfg.get("name_tts")
            or self.channel_cfg.get("name")
            or "nosso canal"
        )
        self.estilo = self.script_cfg.get("style") or self.roteiro_cfg.get("estilo", "educativo e envolvente")
        # CTA de inscrição definido pelo usuário no config (evita o canal ser "alucinado" no texto)
        self.cta = (self.channel_cfg.get("cta_subscribe") or "").strip()
        # Tempo de geração: None = sem limite, para permitir roteiros profundos
        self.timeout = self.ollama_cfg.get("timeout", None)
        # Tokens generosos para roteiro aprofundado (separado do max_tokens usado em traduções)
        self.max_tokens = self.ollama_cfg.get("script_max_tokens", 8000)

    def _chamar_ollama(self, prompt: str) -> str:
        """Faz chamada à API do Ollama com streaming para evitar timeout."""
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            # Qwen3 é "thinking": sem isto ele gasta o orçamento de tokens raciocinando
            # (reasoning_content) e o JSON do roteiro nunca sai completo -> cai no fallback.
            "chat_template_kwargs": {"enable_thinking": False},
        }
        limite = "sem limite" if self.timeout is None else f"{self.timeout}s"
        log.info(f"Chamando Ollama ({self.model}) — timeout: {limite}, max_tokens: {self.max_tokens}...")
        try:
            resp = requests.post(url, json=payload, timeout=self.timeout, stream=True)
            resp.raise_for_status()
            partes = []
            for linha in resp.iter_lines():
                if not linha:
                    continue
                txt = linha.decode("utf-8") if isinstance(linha, bytes) else linha
                if txt.startswith("data: "):
                    txt = txt[6:]
                if txt.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(txt)
                    delta = chunk["choices"][0].get("delta", {})
                    partes.append(delta.get("content") or "")
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
            return "".join(partes).strip()
        except requests.exceptions.ConnectionError:
            raise ConnectionError(
                f"Nao foi possivel conectar ao Ollama em {self.base_url}.\n"
                "Verifique se o Ollama esta rodando: ollama serve"
            )
        except Exception as e:
            raise RuntimeError(f"Erro Ollama: {e}")

    def _prompt_roteiro(self, tema: str, contexto: str) -> str:
        palavras_por_minuto = 130
        total_palavras = self.duracao_min * palavras_por_minuto

        niche = self.config.get("channel", {}).get("niche", "conteúdo para YouTube")

        contexto_real = (contexto or "").strip() or "(sem contexto extra — use seu conhecimento, mas seja específico e evite generalidades)"

        return f"""Você é um roteirista especialista em vídeos de {niche} para YouTube.

TEMA DO VÍDEO: {tema}
CANAL: {self.canal}
ESTILO: {self.estilo}
DURAÇÃO ALVO: {self.duracao_min} minutos ({total_palavras} palavras aproximadamente)
IDIOMA: Português brasileiro

═══════════════ CONTEXTO REAL (BASE FACTUAL — LEIA COM ATENÇÃO) ═══════════════
{contexto_real}
═══════════════════════════════════════════════════════════════════════════════

INSTRUÇÃO CRÍTICA DE PROFUNDIDADE:
- Baseie TODO o roteiro no CONTEXTO REAL acima. Extraia e EXPLIQUE os detalhes concretos: nomes, números, como a coisa funciona por dentro, o que a torna diferente, por que isso importa.
- PROIBIDO encher linguiça com frases vazias do tipo "é um tema fascinante", "impacta nosso dia a dia", "com o avanço da tecnologia". Cada frase deve agregar informação real.
- Se o contexto for técnico, explique o COMO e o PORQUÊ em profundidade, traduzindo o jargão para o público sem perder a substância.
- O espectador deve TERMINAR o vídeo entendendo o assunto de verdade — não com uma impressão superficial.

Crie um roteiro COMPLETO seguindo EXATAMENTE este formato JSON:

{{
  "titulo_video": "Título chamativo e otimizado para SEO (máx 60 chars)",
  "thumb_texto": "Texto ultra-curto para thumbnail (máx 5 palavras em CAPS)",
  "descricao_youtube": "Descrição completa para o YouTube com palavras-chave (2-3 parágrafos)",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6", "tag7", "tag8"],
  "cenas": [
    {{
      "numero": 1,
      "titulo": "Introdução",
      "naracao": "Texto falado pelo narrador nesta cena (2-3 parágrafos envolventes).",
      "palavras_chave_midia": ["keyword for pexels search", "alternative keyword"]
    }},
    {{
      "numero": 2,
      "titulo": "Contexto e Importância",
      "naracao": "Texto falado aqui.",
      "palavras_chave_midia": ["relevant image search term"]
    }},
    {{
      "numero": 3,
      "titulo": "Desenvolvimento",
      "naracao": "Texto falado aqui.",
      "palavras_chave_midia": ["relevant visual keyword"]
    }},
    {{
      "numero": 4,
      "titulo": "Impacto e Novidades",
      "naracao": "Texto falado aqui.",
      "palavras_chave_midia": ["relevant visual keyword"]
    }},
    {{
      "numero": 5,
      "titulo": "Conclusão",
      "naracao": "Conclusao que amarra o conteudo e reforca a ideia principal. NAO peca like nem inscricao aqui — isso e adicionado automaticamente depois.",
      "palavras_chave_midia": ["celebration", "thumbs up"]
    }}
  ]
}}

REGRAS IMPORTANTES:
- PROIBIDO na naracao pedir like, pedir inscricao, mencionar 'se inscreva', 'curta o video' ou citar o nome do canal — esse encerramento e adicionado automaticamente pelo sistema. Repetir isso soa como alucinacao.
- A naracao deve ser natural, fluida e adequada para ser lida em voz alta por um TTS
- NUNCA coloque direções de cena, indicações de voz ou anotações técnicas na naracao
- PROIBIDO na naracao: [Pausa], [PONTO], (voz grave), (música), [efeito], (PAUSA) ou similares
- A naracao deve conter APENAS o texto que será falado, sem nenhuma anotação entre [] ou ()
- Sem símbolos estranhos, emojis ou markdown na naracao
- OBRIGATÓRIO: cada frase deve terminar com ponto final, exclamação ou interrogação
- OBRIGATÓRIO: use vírgulas para separar orações longas — isso melhora a entonação do TTS
- OBRIGATÓRIO: cada cena deve ter NO MÍNIMO {max(int(total_palavras / 5), 80)} palavras na naracao
- OBRIGATÓRIO: cenas 2, 3 e 4 devem contar a história com detalhes, contexto e desenvolvimento real — não apenas introduzir o tema
- O vídeo deve ter um arco narrativo: apresenta → aprofunda → surpreende → conclui
- Total de palavras nas naracoes deve ser aproximadamente {total_palavras}
- As palavras_chave_midia devem ser em INGLÊS para melhor resultado no Pexels
- Responda APENAS com o JSON, sem texto extra antes ou depois"""

    def gerar(self, tema: str, contexto: str = "") -> Roteiro:
        log.info(f"Gerando roteiro para: {tema}")

        prompt = self._prompt_roteiro(tema, contexto)
        resposta_raw = self._chamar_ollama(prompt)

        # Tenta extrair JSON da resposta
        try:
            # Remove eventuais blocos de raciocínio do Qwen3 que vazem no conteúdo
            resposta_clean = re.sub(r"(?s)<think>.*?</think>", "", resposta_raw)

            # Remove possíveis blocos de código markdown
            resposta_clean = re.sub(r"```json\s*|\s*```", "", resposta_clean).strip()

            # Corrige trailing commas (common gemma2 quirk): , followed by } or ]
            resposta_clean = re.sub(r',\s*([}\]])', r'\1', resposta_clean)

            # Encontra o JSON principal
            match = re.search(r'\{[\s\S]*\}', resposta_clean)
            if not match:
                raise ValueError("JSON nao encontrado na resposta")

            data = json.loads(match.group())

        except (json.JSONDecodeError, ValueError) as e:
            log.error(f"Erro ao parsear JSON: {e}")
            log.debug(f"Resposta raw: {resposta_raw[:500]}")
            # Fallback: gera estrutura mínima
            data = self._gerar_fallback(tema, resposta_raw)

        # Monta o objeto Roteiro
        cenas = []
        for c in data.get("cenas", []):
            cenas.append(Cena(
                numero=c.get("numero", len(cenas)+1),
                titulo=c.get("titulo", f"Cena {len(cenas)+1}"),
                naracao=c.get("naracao", ""),
                palavras_chave_midia=c.get("palavras_chave_midia", [tema])
            ))

        # Anexa o CTA configurado pelo usuário na última cena (controlado — nunca alucinado pelo LLM)
        if self.cta and cenas:
            cenas[-1].naracao = (cenas[-1].naracao.rstrip() + " " + self.cta).strip()

        roteiro_completo = "\n\n".join(c.naracao for c in cenas)

        roteiro = Roteiro(
            titulo_video=data.get("titulo_video", f"Tudo sobre {tema}"),
            descricao_youtube=data.get("descricao_youtube", ""),
            tags=data.get("tags", ["ciência", "tecnologia", tema]),
            thumb_texto=data.get("thumb_texto", tema.upper()[:30]),
            cenas=cenas,
            roteiro_completo=roteiro_completo
        )

        log.info(f"Roteiro gerado: '{roteiro.titulo_video}' | {len(cenas)} cenas | "
                 f"{len(roteiro_completo.split())} palavras")
        return roteiro

    def _gerar_fallback(self, tema: str, texto_bruto: str) -> dict:
        """Fallback caso o JSON venha malformado — tenta extrair narações via regex."""
        log.warning("Usando fallback de roteiro (texto bruto como naracao unica)")

        # Tenta extrair campos de naracao mesmo do JSON malformado
        naracoes = re.findall(r'"naracao"\s*:\s*"((?:[^"\\]|\\.)*)"', texto_bruto)
        titulo = re.search(r'"titulo_video"\s*:\s*"((?:[^"\\]|\\.)*)"', texto_bruto)
        thumb = re.search(r'"thumb_texto"\s*:\s*"((?:[^"\\]|\\.)*)"', texto_bruto)

        titulo_video = titulo.group(1) if titulo else f"Tudo sobre {tema} | Ciência & Tecnologia"
        thumb_texto = thumb.group(1) if thumb else tema.upper()[:25]

        if naracoes:
            log.info(f"Fallback extraiu {len(naracoes)} naracao(oes) do JSON malformado")
            cenas = [
                {
                    "numero": i + 1,
                    "titulo": ["Introdução", "Desenvolvimento", "Contexto", "Impacto", "Conclusão"][i]
                              if i < 5 else f"Cena {i+1}",
                    "naracao": n,
                    "palavras_chave_midia": [tema, "technology", "science"]
                }
                for i, n in enumerate(naracoes)
            ]
        else:
            # Último recurso: texto genérico (nunca usa JSON bruto como fala)
            log.warning("Fallback sem narações extraíveis — usando texto genérico")
            cenas = [
                {
                    "numero": 1,
                    "titulo": "Introdução",
                    "naracao": (
                        f"Hoje vamos falar sobre {tema}. "
                        "Este é um tema fascinante que impacta diretamente o nosso dia a dia. "
                        "Fique com a gente até o final para descobrir tudo sobre este assunto."
                    ),
                    "palavras_chave_midia": [tema, "technology", "science"]
                },
                {
                    "numero": 2,
                    "titulo": "Desenvolvimento",
                    "naracao": (
                        f"Vamos explorar os principais aspectos de {tema}. "
                        "Com o avanço da tecnologia, este campo tem evoluído rapidamente. "
                        "Gostou do conteúdo? Deixe seu like e se inscreva no canal!"
                    ),
                    "palavras_chave_midia": ["science discovery", "research"]
                }
            ]

        return {
            "titulo_video": titulo_video,
            "thumb_texto": thumb_texto,
            "descricao_youtube": f"Neste vídeo exploramos tudo sobre {tema}. "
                                  "Deixe seu like e se inscreva no canal!",
            "tags": ["ciência", "tecnologia", tema, "educação", "youtube"],
            "cenas": cenas
        }

    def exibir_roteiro(self, roteiro: Roteiro):
        print("\n" + "="*62)
        print(f"  ROTEIRO GERADO")
        print("="*62)
        print(f"  Titulo : {roteiro.titulo_video}")
        print(f"  Thumb  : {roteiro.thumb_texto}")
        print(f"  Tags   : {', '.join(roteiro.tags[:5])}")
        print(f"  Cenas  : {len(roteiro.cenas)}")
        print(f"  Palavras: {len(roteiro.roteiro_completo.split())}")
        print("="*62)
        for cena in roteiro.cenas:
            print(f"\n  [{cena.numero}] {cena.titulo}")
            print(f"       Midia: {cena.palavras_chave_midia}")
            preview = cena.naracao[:120] + "..." if len(cena.naracao) > 120 else cena.naracao
            print(f"       Texto: {preview}")
        print()
