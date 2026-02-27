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
        self.base_url = self.ollama_cfg.get("base_url", "http://localhost:11434")
        self.model = self.ollama_cfg.get("model", "llama3")
        self.temperature = self.ollama_cfg.get("temperature", 0.8)
        self.duracao_min = self.roteiro_cfg.get("duracao_alvo_minutos", 5)
        self.canal = self.roteiro_cfg.get("canal_nome", "Nosso Canal")
        self.estilo = self.roteiro_cfg.get("estilo", "educativo e envolvente")

    def _chamar_ollama(self, prompt: str) -> str:
        """Faz chamada à API do Ollama com streaming para evitar timeout."""
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": self.temperature,
                "num_predict": 3000
            }
        }
        log.info(f"Chamando Ollama ({self.model})...")
        try:
            resp = requests.post(url, json=payload, timeout=600, stream=True)
            resp.raise_for_status()
            partes = []
            for linha in resp.iter_lines():
                if not linha:
                    continue
                try:
                    chunk = json.loads(linha)
                    partes.append(chunk.get("response", ""))
                    if chunk.get("done"):
                        break
                except json.JSONDecodeError:
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

        return f"""Você é um roteirista especialista em vídeos educativos de ciência e tecnologia para YouTube.

TEMA DO VÍDEO: {tema}
CONTEXTO ADICIONAL: {contexto}
CANAL: {canal_nome if (canal_nome := self.canal) else "Ciência & Tech"}
ESTILO: {self.estilo}
DURAÇÃO ALVO: {self.duracao_min} minutos ({total_palavras} palavras aproximadamente)
IDIOMA: Português brasileiro

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
      "naracao": "Texto falado aqui...",
      "palavras_chave_midia": ["relevant image search term"]
    }},
    {{
      "numero": 3,
      "titulo": "Como Funciona",
      "naracao": "Texto falado aqui...",
      "palavras_chave_midia": ["technology visualization", "science lab"]
    }},
    {{
      "numero": 4,
      "titulo": "Impacto e Futuro",
      "naracao": "Texto falado aqui...",
      "palavras_chave_midia": ["future technology", "innovation"]
    }},
    {{
      "numero": 5,
      "titulo": "Conclusão",
      "naracao": "Finalizacao com call-to-action para curtir e se inscrever no canal {self.canal}.",
      "palavras_chave_midia": ["science conclusion", "discovery"]
    }}
  ]
}}

REGRAS IMPORTANTES:
- A naracao deve ser natural, fluida e adequada para ser lida em voz alta por um TTS
- NUNCA coloque direções de cena, indicações de voz ou anotações técnicas na naracao
- PROIBIDO na naracao: [Pausa], [PONTO], (voz grave), (música), [efeito], (PAUSA) ou similares
- A naracao deve conter APENAS o texto que será falado, sem nenhuma anotação entre [] ou ()
- Sem símbolos estranhos, emojis ou markdown na naracao
- Total de palavras nas naracoes deve ser aproximadamente {total_palavras}
- As palavras_chave_midia devem ser em INGLÊS para melhor resultado no Pexels
- Responda APENAS com o JSON, sem texto extra antes ou depois"""

    def gerar(self, tema: str, contexto: str = "") -> Roteiro:
        log.info(f"Gerando roteiro para: {tema}")

        prompt = self._prompt_roteiro(tema, contexto)
        resposta_raw = self._chamar_ollama(prompt)

        # Tenta extrair JSON da resposta
        try:
            # Remove possíveis blocos de código markdown
            resposta_clean = re.sub(r"```json\s*|\s*```", "", resposta_raw).strip()

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
