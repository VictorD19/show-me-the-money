"""
Coleta de noticias e analise de sentimento em tempo real.

Fontes:
- CryptoPanic API (noticias cripto)
- Alternative.me Fear & Greed Index
- Whale Alert API (transacoes grandes)
- FinBERT / DistilBERT para analise de sentimento
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import requests
from loguru import logger

try:
    from transformers import pipeline
    _TRANSFORMERS_AVAILABLE = True
except ImportError:
    _TRANSFORMERS_AVAILABLE = False
    logger.warning("transformers nao instalado — analise de sentimento desabilitada")

try:
    from config import CRYPTOPANIC_API_KEY, WHALE_ALERT_API_KEY
except ImportError:
    CRYPTOPANIC_API_KEY = ""
    WHALE_ALERT_API_KEY = ""
    logger.warning("config.py nao encontrado — usando chaves de API vazias")


class NewsCollector:
    """Coleta noticias cripto e calcula sentimento agregado."""

    _CRYPTOPANIC_URL = "https://cryptopanic.com/api/v1/posts/"
    _FEAR_GREED_URL = "https://api.alternative.me/fng/"
    _WHALE_ALERT_URL = "https://api.whale-alert.io/v1/transactions"

    def __init__(self, timeout: int = 10) -> None:
        self._timeout = timeout
        self._sentiment_pipeline: Optional[Any] = None
        self._news_cache: List[Dict[str, Any]] = []
        self._fear_greed_cache: Optional[Dict[str, Any]] = None
        self._fear_greed_ts: float = 0.0
        self._polling_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Sentiment model (lazy load)
    # ------------------------------------------------------------------

    def _load_sentiment_model(self) -> None:
        """Carrega o modelo de sentimento na primeira utilizacao."""
        if self._sentiment_pipeline is not None:
            return
        if not _TRANSFORMERS_AVAILABLE:
            logger.warning("Pipeline de sentimento indisponivel (transformers ausente)")
            return
        try:
            self._sentiment_pipeline = pipeline(
                "sentiment-analysis",
                model="ProsusAI/finbert",
                tokenizer="ProsusAI/finbert",
                device=-1,  # CPU
            )
            logger.info("Modelo FinBERT carregado com sucesso")
        except Exception as exc:
            logger.error(f"Falha ao carregar FinBERT, tentando distilbert: {exc}")
            try:
                self._sentiment_pipeline = pipeline(
                    "sentiment-analysis",
                    model="distilbert-base-uncased-finetuned-sst-2-english",
                    device=-1,
                )
                logger.info("Modelo DistilBERT carregado como fallback")
            except Exception as exc2:
                logger.error(f"Nenhum modelo de sentimento disponivel: {exc2}")

    # ------------------------------------------------------------------
    # CryptoPanic
    # ------------------------------------------------------------------

    def get_cryptopanic_news(
        self, pares: Optional[List[str]] = None, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Busca noticias recentes da API CryptoPanic.

        Args:
            pares: Lista de moedas (ex: ["BTC", "ETH"]). Se None, usa BTC,ETH,XRP.
            limit: Quantidade maxima de noticias.

        Returns:
            Lista de dicts com titulo, url, timestamp e votos.
        """
        if not CRYPTOPANIC_API_KEY:
            logger.warning("CRYPTOPANIC_API_KEY nao definida — retornando mock")
            return self._mock_cryptopanic_news(pares or ["BTC", "ETH", "XRP"])

        currencies = ",".join(pares) if pares else "BTC,ETH,XRP"
        params = {
            "auth_token": CRYPTOPANIC_API_KEY,
            "currencies": currencies,
            "kind": "news",
            "public": "true",
        }
        try:
            resp = requests.get(
                self._CRYPTOPANIC_URL, params=params, timeout=self._timeout
            )
            resp.raise_for_status()
            data = resp.json()
            results = []
            for item in data.get("results", [])[:limit]:
                votes = item.get("votes", {})
                results.append(
                    {
                        "titulo": item.get("title", ""),
                        "url": item.get("url", ""),
                        "timestamp": item.get("published_at", ""),
                        "votos_positivos": votes.get("positive", 0),
                        "votos_negativos": votes.get("negative", 0),
                        "moedas": [
                            c.get("code", "") for c in item.get("currencies", [])
                        ],
                    }
                )
            self._news_cache = results
            logger.debug(f"CryptoPanic: {len(results)} noticias obtidas")
            return results
        except Exception as exc:
            logger.error(f"Erro ao buscar CryptoPanic: {exc}")
            return self._mock_cryptopanic_news(pares or ["BTC", "ETH", "XRP"])

    @staticmethod
    def _mock_cryptopanic_news(pares: List[str]) -> List[Dict[str, Any]]:
        """Retorna noticias mock quando API nao esta disponivel."""
        agora = datetime.now(timezone.utc).isoformat()
        return [
            {
                "titulo": f"Mercado de {par} estavel nas ultimas horas",
                "url": "https://example.com/mock",
                "timestamp": agora,
                "votos_positivos": 5,
                "votos_negativos": 2,
                "moedas": [par],
            }
            for par in pares
        ]

    # ------------------------------------------------------------------
    # Fear & Greed Index
    # ------------------------------------------------------------------

    def get_fear_greed_index(self) -> Dict[str, Any]:
        """Busca o indice Fear & Greed atual.

        Returns:
            Dict com 'valor' (0-100) e 'classificacao' (str).
        """
        # Cache de 5 minutos
        if self._fear_greed_cache and (time.time() - self._fear_greed_ts < 300):
            return self._fear_greed_cache

        try:
            resp = requests.get(
                self._FEAR_GREED_URL,
                params={"limit": 1},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            item = data.get("data", [{}])[0]
            result = {
                "valor": int(item.get("value", 50)),
                "classificacao": item.get("value_classification", "Neutral"),
                "timestamp": item.get("timestamp", ""),
            }
            self._fear_greed_cache = result
            self._fear_greed_ts = time.time()
            logger.debug(f"Fear & Greed: {result['valor']} ({result['classificacao']})")
            return result
        except Exception as exc:
            logger.error(f"Erro ao buscar Fear & Greed: {exc}")
            return {"valor": 50, "classificacao": "Neutral", "timestamp": ""}

    # ------------------------------------------------------------------
    # Whale Alert
    # ------------------------------------------------------------------

    def get_whale_alerts(
        self, min_value_usd: int = 1_000_000
    ) -> List[Dict[str, Any]]:
        """Busca alertas de transacoes grandes via Whale Alert API.

        Args:
            min_value_usd: Valor minimo em USD para filtrar transacoes.

        Returns:
            Lista de dicts com informacoes da transacao.
        """
        if not WHALE_ALERT_API_KEY:
            logger.warning("WHALE_ALERT_API_KEY nao definida — retornando mock")
            return self._mock_whale_alerts()

        now = int(time.time())
        params = {
            "api_key": WHALE_ALERT_API_KEY,
            "min_value": min_value_usd,
            "start": now - 3600,  # ultima hora
            "cursor": "",
        }
        try:
            resp = requests.get(
                self._WHALE_ALERT_URL, params=params, timeout=self._timeout
            )
            resp.raise_for_status()
            data = resp.json()
            results = []
            for tx in data.get("transactions", []):
                results.append(
                    {
                        "hash": tx.get("hash", ""),
                        "blockchain": tx.get("blockchain", ""),
                        "symbol": tx.get("symbol", ""),
                        "amount": tx.get("amount", 0),
                        "amount_usd": tx.get("amount_usd", 0),
                        "from_owner": tx.get("from", {}).get("owner", "unknown"),
                        "to_owner": tx.get("to", {}).get("owner", "unknown"),
                        "timestamp": tx.get("timestamp", 0),
                    }
                )
            logger.debug(f"Whale Alert: {len(results)} transacoes encontradas")
            return results
        except Exception as exc:
            logger.error(f"Erro ao buscar Whale Alert: {exc}")
            return self._mock_whale_alerts()

    @staticmethod
    def _mock_whale_alerts() -> List[Dict[str, Any]]:
        """Retorna alertas mock quando API nao esta disponivel."""
        return [
            {
                "hash": "mock_hash",
                "blockchain": "bitcoin",
                "symbol": "BTC",
                "amount": 100,
                "amount_usd": 5_000_000,
                "from_owner": "unknown",
                "to_owner": "binance",
                "timestamp": int(time.time()),
            }
        ]

    # ------------------------------------------------------------------
    # Analise de sentimento
    # ------------------------------------------------------------------

    def analyze_sentiment(self, texto: str) -> float:
        """Analisa sentimento de um texto usando FinBERT.

        Args:
            texto: Texto para analise.

        Returns:
            Score entre -1.0 (muito negativo) e +1.0 (muito positivo).
        """
        self._load_sentiment_model()
        if self._sentiment_pipeline is None:
            return 0.0

        try:
            # Truncar para 512 tokens (limite do modelo)
            resultado = self._sentiment_pipeline(texto[:512])[0]
            label = resultado.get("label", "").lower()
            score = resultado.get("score", 0.5)

            # FinBERT retorna 'positive', 'negative', 'neutral'
            if label in ("positive", "POSITIVE"):
                return score
            elif label in ("negative", "NEGATIVE"):
                return -score
            else:
                return 0.0
        except Exception as exc:
            logger.error(f"Erro na analise de sentimento: {exc}")
            return 0.0

    # ------------------------------------------------------------------
    # Score agregado
    # ------------------------------------------------------------------

    def get_news_sentiment_score(self, par: str) -> float:
        """Retorna score agregado de sentimento das ultimas noticias do par.

        Usa media ponderada por recencia (noticias mais recentes pesam mais).

        Args:
            par: Simbolo da moeda (ex: "BTC").

        Returns:
            Score medio entre -1.0 e +1.0.
        """
        noticias = self.get_cryptopanic_news([par], limit=10)
        if not noticias:
            return 0.0

        scores = []
        pesos = []
        agora = time.time()

        for i, noticia in enumerate(noticias):
            # Peso decrescente por posicao (mais recente = mais peso)
            peso = 1.0 / (i + 1)

            # Score por votos (rapido, sem modelo)
            positivos = noticia.get("votos_positivos", 0)
            negativos = noticia.get("votos_negativos", 0)
            total_votos = positivos + negativos
            if total_votos > 0:
                vote_score = (positivos - negativos) / total_votos
            else:
                vote_score = 0.0

            # Score por NLP do titulo
            nlp_score = self.analyze_sentiment(noticia.get("titulo", ""))

            # Combina votos + NLP (60% NLP, 40% votos)
            score_combinado = 0.6 * nlp_score + 0.4 * vote_score

            scores.append(score_combinado)
            pesos.append(peso)

        if not pesos:
            return 0.0

        total_peso = sum(pesos)
        score_final = sum(s * p for s, p in zip(scores, pesos)) / total_peso
        logger.debug(f"Sentimento agregado para {par}: {score_final:.4f}")
        return round(score_final, 4)

    # ------------------------------------------------------------------
    # Polling assincrono
    # ------------------------------------------------------------------

    async def start_news_polling(
        self,
        callback: Callable[[List[Dict[str, Any]]], Any],
        intervalo_segundos: int = 300,
    ) -> None:
        """Loop assincrono que busca noticias periodicamente.

        Args:
            callback: Funcao chamada com a lista de noticias a cada ciclo.
            intervalo_segundos: Intervalo entre buscas (default 5 min).
        """
        logger.info(
            f"Iniciando polling de noticias a cada {intervalo_segundos}s"
        )
        while True:
            try:
                noticias = self.get_cryptopanic_news()
                fear_greed = self.get_fear_greed_index()
                payload = {
                    "noticias": noticias,
                    "fear_greed": fear_greed,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                await asyncio.to_thread(callback, payload)
            except Exception as exc:
                logger.error(f"Erro no polling de noticias: {exc}")

            await asyncio.sleep(intervalo_segundos)

    def stop_news_polling(self) -> None:
        """Para o polling de noticias se estiver rodando."""
        if self._polling_task and not self._polling_task.done():
            self._polling_task.cancel()
            logger.info("Polling de noticias parado")
