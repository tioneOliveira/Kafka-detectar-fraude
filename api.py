"""API de inferência para detecção de fraudes financeiras."""

import os

import joblib
import pandas as pd
from fastapi import FastAPI
from pydantic import BaseModel

VERSAO = os.getenv("VERSAO", "dev")
modelo = joblib.load("modelo_fraude.pkl")

app = FastAPI(
    title="API de Detecção de Fraudes",
    description="Classifica transações financeiras com um modelo scikit-learn.",
    version=VERSAO,
)


class Transacao(BaseModel):
    step: int
    type: str
    amount: float
    isFlaggedFraud: int = 0


class Resultado(BaseModel):
    fraude: bool
    probabilidade_fraude: float


@app.get("/")
def raiz():
    return {
        "servico": "api-de-deteccao-de-fraudes",
        "versao": VERSAO,
        "endpoints": ["/health", "/versao", "/prediz", "/docs"],
    }


@app.get("/health")
def health():
    return {"status": "ok", "modelo_carregado": modelo is not None}


@app.get("/versao")
def versao():
    return {"versao": VERSAO}


@app.post("/prediz", response_model=Resultado)
def prediz(transacao: Transacao):
    dados = pd.DataFrame([transacao.model_dump()])
    probabilidade = float(modelo.predict_proba(dados)[0][1])
    return Resultado(
        fraude=probabilidade >= 0.5,
        probabilidade_fraude=round(probabilidade, 4),
    )
