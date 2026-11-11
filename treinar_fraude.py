"""Treina o classificador de fraude a partir do CSV do Kaggle.

Uso:
    python treinar_fraude.py --arquivo fraud.csv

O arquivo modelo_fraude.pkl gerado por este script é carregado pela API.
"""

import argparse
from pathlib import Path

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

FEATURES_NUMERICAS = ["step", "amount", "isFlaggedFraud"]
FEATURES_CATEGORICAS = ["type"]
FEATURES = FEATURES_NUMERICAS + FEATURES_CATEGORICAS


def treinar(arquivo: Path, saida: Path) -> None:
    dados = pd.read_csv(arquivo)
    colunas_obrigatorias = set(FEATURES + ["isFraud"])
    ausentes = sorted(colunas_obrigatorias - set(dados.columns))
    if ausentes:
        raise ValueError(
            "O CSV não possui as colunas obrigatórias: " + ", ".join(ausentes)
        )

    dados = dados[FEATURES + ["isFraud"]].dropna()
    X = dados[FEATURES]
    y = dados["isFraud"].astype(int)

    if y.nunique() != 2:
        raise ValueError("A coluna isFraud precisa conter as classes 0 e 1.")

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.2,
        random_state=42,
        stratify=y,
    )

    preprocessador = ColumnTransformer(
        [
            ("numericas", StandardScaler(), FEATURES_NUMERICAS),
            (
                "tipo",
                OneHotEncoder(handle_unknown="ignore"),
                FEATURES_CATEGORICAS,
            ),
        ]
    )

    modelo = Pipeline(
        [
            ("preprocessamento", preprocessador),
            (
                "classificador",
                LogisticRegression(
                    max_iter=1000,
                    class_weight="balanced",
                ),
            ),
        ]
    )
    modelo.fit(X_train, y_train)

    probabilidades = modelo.predict_proba(X_test)[:, 1]
    predicoes = (probabilidades >= 0.5).astype(int)
    print(classification_report(y_test, predicoes, zero_division=0))
    print(f"ROC-AUC: {roc_auc_score(y_test, probabilidades):.4f}")

    joblib.dump(modelo, saida)
    print(f"Modelo salvo em {saida}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arquivo", type=Path, default=Path("fraud.csv"))
    parser.add_argument(
        "--saida", type=Path, default=Path("modelo_fraude.pkl")
    )
    args = parser.parse_args()
    treinar(args.arquivo, args.saida)


if __name__ == "__main__":
    main()
