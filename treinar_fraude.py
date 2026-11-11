"""Treina o classificador de fraude a partir do CSV do Kaggle.

Uso:
    python treinar_fraude.py --arquivo fraud.csv

Se o arquivo não existir, ele será baixado automaticamente do Kaggle.
O arquivo modelo_fraude.pkl gerado por este script é carregado pela API.
"""

import argparse
import os
from pathlib import Path
import shutil
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from zipfile import BadZipFile, ZipFile

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
URL_DATASET = (
    "https://www.kaggle.com/api/v1/datasets/download/"
    "sriharshaeedala/financial-fraud-detection-dataset"
)


def baixar_dataset(arquivo: Path) -> None:
    """Baixa e extrai o CSV do Kaggle para o caminho informado."""
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo_temporario = None
    csv_temporario = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=".zip",
            prefix="fraud-dataset-",
            dir=arquivo.parent,
            delete=False,
        ) as destino_zip:
            arquivo_temporario = Path(destino_zip.name)
            try:
                with urlopen(URL_DATASET, timeout=120) as resposta:
                    shutil.copyfileobj(resposta, destino_zip, length=1024 * 1024)
            except (HTTPError, URLError) as erro:
                raise RuntimeError(
                    "Não foi possível baixar o dataset do Kaggle. "
                    "Verifique sua conexão e, se solicitado, configure "
                    "KAGGLE_USERNAME e KAGGLE_KEY."
                ) from erro

        try:
            with ZipFile(arquivo_temporario) as pacote:
                csvs = sorted(
                    nome
                    for nome in pacote.namelist()
                    if nome.lower().endswith(".csv") and not nome.endswith("/")
                )
                if not csvs:
                    raise RuntimeError("O pacote do Kaggle não contém um arquivo CSV.")

                with pacote.open(csvs[0]) as origem, tempfile.NamedTemporaryFile(
                    mode="wb",
                    suffix=".csv",
                    prefix="fraud-",
                    dir=arquivo.parent,
                    delete=False,
                ) as destino_csv:
                    csv_temporario = Path(destino_csv.name)
                    shutil.copyfileobj(origem, destino_csv, length=1024 * 1024)
        except BadZipFile as erro:
            raise RuntimeError("O download do dataset do Kaggle não é um ZIP válido.") from erro

        os.replace(csv_temporario, arquivo)
        csv_temporario = None
        print(f"Dataset baixado para {arquivo}")
    finally:
        if arquivo_temporario is not None:
            arquivo_temporario.unlink(missing_ok=True)
        if csv_temporario is not None:
            csv_temporario.unlink(missing_ok=True)


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
    if not args.arquivo.exists():
        baixar_dataset(args.arquivo)
    treinar(args.arquivo, args.saida)


if __name__ == "__main__":
    main()
